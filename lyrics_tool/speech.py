"""원어 발음 듣기 — 가사 원문을 줄 단위·곡 전체로 읽은 MP3를 만든다.

음성은 edge-tts(Microsoft Edge 온라인 신경망 음성)로 만든다. 원문 가사가 Microsoft로 전송되며 인터넷이 필요하다.
한 줄씩 따로 합성해 디스크에 캐시하고, 곡 전체는 줄 MP3를 이어 붙이면서 줄 사이에 무음 프레임을 넣는다.
(edge-tts는 고정 비트레이트 MP3를 주므로 프레임을 그대로 이어 붙여도 되고, 프레임 수로 길이를 정확히 안다.)

줄 사이 쉼 (값은 코드, 화면 이름은 i18n `gap_<값>`)
  GAP_SHORT : 짧게 (0.4초) — 노래처럼 이어 듣기
  GAP_PAUSE : 1.5초
  GAP_ECHO  : 따라 말하기 — 그 줄 길이만큼 + 0.5초 쉬어 바로 따라 해 볼 수 있게
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .core import Doc

VOICES: dict[str, tuple[str, str]] = {  # 언어: (여성, 남성)
    "en": ("en-US-AvaNeural", "en-US-AndrewNeural"),
    "ja": ("ja-JP-NanamiNeural", "ja-JP-KeitaNeural"),
    "zh": ("zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"),
    "ko": ("ko-KR-SunHiNeural", "ko-KR-InJoonNeural"),
    "es": ("es-ES-ElviraNeural", "es-ES-AlvaroNeural"),
    "fr": ("fr-FR-DeniseNeural", "fr-FR-HenriNeural"),
    "de": ("de-DE-KatjaNeural", "de-DE-ConradNeural"),
    "pt": ("pt-BR-FranciscaNeural", "pt-BR-AntonioNeural"),
    "it": ("it-IT-ElsaNeural", "it-IT-DiegoNeural"),
    "ru": ("ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"),
    "vi": ("vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural"),
    "th": ("th-TH-PremwadeeNeural", "th-TH-NiwatNeural"),
    "id": ("id-ID-GadisNeural", "id-ID-ArdiNeural"),
}
FEMALE, MALE = "female", "male"

GAP_SHORT, GAP_PAUSE, GAP_ECHO = "short", "pause", "echo"
GAPS = [GAP_SHORT, GAP_PAUSE, GAP_ECHO]
STANZA_EXTRA = 0.8  # 빈 줄(연 구분)에서 더 쉬는 시간

CACHE_DIR = Path(tempfile.gettempdir()) / "lyrics-jikdok" / "tts"
PARALLEL = 4


class SpeechError(RuntimeError):
    """합성 실패. args[0] = 사람이 읽을 사유."""


def available() -> bool:
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        return False
    return True


def voice_for(lang: str, gender: str = FEMALE) -> str:
    pair = VOICES.get(lang, VOICES["en"])
    return pair[1] if gender == MALE else pair[0]


def rate_str(rate: float) -> str:
    """배속(1.0 = 보통) → edge-tts 형식 '+0%'"""
    pct = round((float(rate) - 1.0) * 100)
    return f"{pct:+d}%"


# ---------------------------------------------------------------- MP3 프레임

_BITRATES = {  # (MPEG-1 여부) → Layer III 비트레이트 표 (kbps)
    True: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    False: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}
_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


@dataclass
class Frame:
    header: bytes
    length: int
    seconds: float


def _frame_at(data: bytes, i: int) -> Frame | None:
    if i + 4 > len(data) or data[i] != 0xFF or data[i + 1] & 0xE0 != 0xE0:
        return None
    ver = (data[i + 1] >> 3) & 3  # 3 = MPEG-1, 2 = MPEG-2, 0 = MPEG-2.5
    layer = (data[i + 1] >> 1) & 3
    br_i, sr_i, pad = data[i + 2] >> 4, (data[i + 2] >> 2) & 3, (data[i + 2] >> 1) & 1
    if ver == 1 or layer != 1 or br_i in (0, 15) or sr_i == 3:  # Layer III만
        return None
    mpeg1 = ver == 3
    bitrate, rate = _BITRATES[mpeg1][br_i] * 1000, _RATES[ver][sr_i]
    samples = 1152 if mpeg1 else 576
    length = (144 if mpeg1 else 72) * bitrate // rate + pad
    return Frame(bytes(data[i:i + 4]), length, samples / rate)


def _skip_id3(data: bytes) -> int:
    if data[:3] == b"ID3" and len(data) >= 10:
        size = (data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14 | (data[8] & 0x7F) << 7 | (data[9] & 0x7F)
        return 10 + size
    return 0


def frames(data: bytes) -> list[Frame]:
    out, i = [], _skip_id3(data)
    while i < len(data):
        f = _frame_at(data, i)
        if f is None:
            i += 1  # 깨진 바이트는 건너뛴다
            continue
        out.append(f)
        i += f.length
    return out


def duration(data: bytes) -> float:
    return sum(f.seconds for f in frames(data))


def silence(template: bytes, seconds: float) -> bytes:
    """template MP3와 같은 형식의 무음. 부가 정보가 모두 0인 프레임은 소리 없이 디코딩된다."""
    fs = frames(template)
    if not fs or seconds <= 0:
        return b""
    f = fs[0]
    header = bytearray(f.header)
    header[2] &= ~0x02  # 패딩 비트 끔
    plain = _frame_at(bytes(header) + b"\0" * 4, 0)
    one = bytes(header) + b"\0" * (plain.length - 4)
    return one * max(1, round(seconds / plain.seconds))


# ---------------------------------------------------------------- 합성


async def _synth_one(text: str, voice: str, rate: str) -> bytes:
    import edge_tts

    data = bytearray()
    async for chunk in edge_tts.Communicate(text, voice, rate=rate).stream():
        if chunk["type"] == "audio":
            data += chunk["data"]
    return bytes(data)


def _cache_path(text: str, voice: str, rate: str) -> Path:
    key = hashlib.sha1(f"{voice}|{rate}|{text}".encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.mp3"


async def _synth_cached(text: str, voice: str, rate: str, sem: asyncio.Semaphore) -> bytes:
    path = _cache_path(text, voice, rate)
    if path.exists():
        return path.read_bytes()
    async with sem:
        last: Exception | None = None
        for _ in range(3):
            try:
                data = await _synth_one(text, voice, rate)
                if data:
                    break
            except Exception as e:  # 네트워크·서비스 오류
                last = e
            await asyncio.sleep(0.6)
        else:
            raise SpeechError(str(last) if last else "empty audio")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return data


def synth_many(texts: list[str], voice: str, rate: str) -> list[bytes]:
    """여러 줄을 동시에(최대 PARALLEL개) 합성한다. 같은 문장은 캐시에서 꺼낸다."""
    if not available():
        raise SpeechError("edge-tts is not installed (pip install edge-tts)")

    async def run():
        sem = asyncio.Semaphore(PARALLEL)
        uniq = list(dict.fromkeys(texts))
        got = await asyncio.gather(*(_synth_cached(t, voice, rate, sem) for t in uniq))
        table = dict(zip(uniq, got))
        return [table[t] for t in texts]

    return asyncio.run(run())


# ---------------------------------------------------------------- 곡 단위


@dataclass
class Timing:
    line: int  # 1-based 줄 번호
    start: float
    end: float


def song_lines(doc: Doc) -> list[tuple[int, str]]:
    return [(i, s.strip()) for i, s in enumerate(doc.sources, 1) if s.strip()]


def build_song(doc: Doc, clips: dict[int, bytes], gap: str = GAP_SHORT) -> tuple[bytes, list[Timing]]:
    """줄 MP3들을 이어 곡 전체 MP3와 줄별 재생 구간을 만든다. clips: {줄 번호: MP3}"""
    if not clips:
        return b"", []
    template = next(iter(clips.values()))
    out = bytearray(silence(template, 0.3))
    t = duration(bytes(out))
    timings: list[Timing] = []
    prev_blank = False
    for i, src in enumerate(doc.sources, 1):
        if not src.strip():
            prev_blank = True
            continue
        if prev_blank and timings:
            pad = silence(template, STANZA_EXTRA)
            out += pad
            t += duration(pad)
        prev_blank = False
        clip = clips[i]
        d = duration(clip)
        out += clip
        timings.append(Timing(i, round(t, 3), round(t + d, 3)))
        t += d
        rest = {GAP_SHORT: 0.4, GAP_PAUSE: 1.5, GAP_ECHO: d + 0.5}.get(gap, 0.4)
        pad = silence(template, rest)
        out += pad
        t += duration(pad)
    return bytes(out), timings


def speak_song(doc: Doc, gender: str = FEMALE, rate: float = 1.0, gap: str = GAP_SHORT,
               ) -> tuple[bytes, list[Timing], dict[int, bytes]]:
    """(곡 전체 MP3, 줄별 구간, {줄 번호: 줄 MP3})"""
    lines = song_lines(doc)
    voice = voice_for(doc.lang, gender)
    clips = dict(zip((i for i, _ in lines), synth_many([s for _, s in lines], voice, rate_str(rate))))
    song, timings = build_song(doc, clips, gap)
    return song, timings, clips


def speak_line(doc: Doc, line_no: int, gender: str = FEMALE, rate: float = 1.0) -> bytes:
    text = doc.sources[line_no - 1].strip() if 0 < line_no <= len(doc.sources) else ""
    if not text:
        raise SpeechError(f"line {line_no} is blank")
    return synth_many([text], voice_for(doc.lang, gender), rate_str(rate))[0]


def lines_zip(doc: Doc, clips: dict[int, bytes]) -> bytes:
    """줄별 MP3 묶음. 파일 이름에 줄 번호와 원문 앞부분을 넣어 목록에서 바로 찾게 한다."""
    import re

    width = max(2, len(str(len(doc.sources))))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:  # MP3는 이미 압축돼 있다
        for i, data in clips.items():
            head = re.sub(r'[\\/:*?"<>|\s]+', "_", doc.sources[i - 1].strip()).strip("._")[:24]
            z.writestr(f"{i:0{width}d}_{head or 'line'}.mp3", data)
    return buf.getvalue()
