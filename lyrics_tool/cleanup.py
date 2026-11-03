"""붙여넣은 가사·LRC 파일 정리.

웹에서 복사한 가사에는 번역에 방해되는 것들이 섞여 있다.
- LRC 타임스탬프 [01:23.45], 메타데이터 [ti:...] [ar:...]
- 구간 표시 [Chorus] [Verse 1] 【サビ】 (副歌) → 연 구분(빈 줄)으로 바꿈
- 크레딧 줄 作词：… 作曲：… 編曲：…
- 가사 사이트 잔여물 "You might also like", "123Embed"
- 원문과 한국어 번역이 번갈아 있는 가사 → 한국어 줄 제거 (번역 언어가 한국어일 때만, drop_hangul)
정리 결과와 함께 무엇을 바꿨는지 보고한다.
"""

from __future__ import annotations

import re
from pathlib import Path
from statistics import median

from .i18n import t as _t

_TS = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")
_LRC_META = re.compile(r"^\s*\[(ti|ar|al|au|by|offset|length|re|ve|tool|#)\s*:[^\]]*\]\s*$", re.I)

_SECTION_WORDS = (
    r"chorus|pre-?chorus|post-?chorus|verse|bridge|intro|outro|hook|refrain|interlude|instrumental|"
    r"breakdown|drop|rap|skit|"
    r"サビ|[ABCD]メロ|間奏|イントロ|アウトロ|大サビ|落ちサビ|"
    r"副歌|主歌|前奏|间奏|間奏|尾奏|桥段|過門|过门|"
    r"후렴|벌스|브릿지|간주|인트로|아웃트로|훅"
)
_SECTION = re.compile(
    rf"^\s*(?:[\[【(（〈<]\s*(?:{_SECTION_WORDS})[^\]】)）〉>]{{0,40}}[\]】)）〉>]"
    rf"|(?:{_SECTION_WORDS})\s*\d*\s*[:：])\s*$",
    re.I,
)
_CREDIT = re.compile(
    r"^\s*(作词|作詞|作曲|编曲|編曲|词|詞|曲|制作人|製作人|监制|監製|和声|和聲|混音|母带|吉他|贝斯|鼓|弦乐|"
    r"OP|SP|出品|发行|發行|Lyrics?|Lyricist|Composer|Composed by|Written by|Arranged by|Produced by)"
    r"\s*(by)?\s*[:：]",
    re.I,
)
_JUNK_LINE = re.compile(r"^\s*(You might also like|See .* Live|Get tickets as low as .*|\d+\s*Contributors?.*)\s*$", re.I)
_EMBED_TAIL = re.compile(r"\s*\d*\s*Embed\s*$")

_HANGUL = re.compile(r"[가-힣]")
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def _hangul_ratio(line: str) -> float:
    letters = _LETTER.findall(line)
    return len(_HANGUL.findall(line)) / len(letters) if letters else 0.0


def _ts_seconds(m: re.Match) -> float:
    frac = m.group(3) or "0"
    return int(m.group(1)) * 60 + int(m.group(2)) + int(frac) / (10 ** len(frac))


def clean_lyrics(text: str, ui: str = "en", drop_hangul: bool = True) -> tuple[str, list[str]]:
    """가사를 정리하고 (정리된 가사, 변경 내역)을 반환한다. 내역은 ui 언어 문장."""
    report: list[str] = []
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    # 내용 줄 사이에 빈 줄이 있는지 (파일 끝 줄바꿈은 제외)
    body = [l for l in raw if l.strip() and not _LRC_META.match(l)]
    first = next((k for k, l in enumerate(raw) if l.strip()), 0)
    last = max((k for k, l in enumerate(raw) if l.strip()), default=0)
    had_blank = len(body) > 0 and any(not l.strip() for l in raw[first : last + 1])

    lines: list[str] = []
    times: list[float | None] = []
    n_ts = n_meta = n_sec = n_credit = n_junk = 0
    for line in raw:
        if _LRC_META.match(line):
            n_meta += 1
            continue
        stamps = list(_TS.finditer(line))
        t = None
        if stamps and line.lstrip().startswith("["):
            t = _ts_seconds(stamps[0])
            line = _TS.sub("", line)
            n_ts += 1
        if _EMBED_TAIL.search(line) and line.strip() != "Embed":
            line = _EMBED_TAIL.sub("", line)
            n_junk += 1
        line = line.strip()
        if _SECTION.match(line):
            n_sec += 1
            line = ""  # 구간 표시는 연 구분으로
        elif _CREDIT.match(line):
            n_credit += 1
            continue
        elif _JUNK_LINE.match(line):
            n_junk += 1
            continue
        lines.append(line)
        times.append(t)

    # LRC는 빈 줄이 없어 연 구분이 사라진다 → 시간 간격이 긴 곳에 빈 줄을 넣는다
    if n_ts and not had_blank:
        stamped = [(k, t) for k, t in enumerate(times) if t is not None and lines[k]]
        gaps = [b[1] - a[1] for a, b in zip(stamped, stamped[1:]) if b[1] > a[1]]
        if len(gaps) >= 4:
            limit = max(6.0, median(gaps) * 1.8)
            breaks = {b[0] for a, b in zip(stamped, stamped[1:]) if b[1] - a[1] >= limit}
            if breaks:
                out = []
                for k, l in enumerate(lines):
                    if k in breaks:
                        out.append("")
                    out.append(l)
                lines = out
                report.append(_t(ui, "clean_breaks", n=len(breaks)))

    # 원문과 한국어 번역이 섞인 경우 한국어 줄 제거 (원문이 한국어가 아닐 때만)
    nonblank = [l for l in lines if l]
    ko_lines = [l for l in nonblank if _hangul_ratio(l) > 0.5]
    if drop_hangul and nonblank and 0.2 <= len(ko_lines) / len(nonblank) <= 0.6:
        lines = [l for l in lines if not l or _hangul_ratio(l) <= 0.5]
        report.append(_t(ui, "clean_hangul", n=len(ko_lines)))

    # 빈 줄 정리: 연속 빈 줄은 하나로, 앞뒤 빈 줄 제거
    out: list[str] = []
    for l in lines:
        if not l and (not out or not out[-1]):
            continue
        out.append(l)
    while out and not out[-1]:
        out.pop()

    counts = [
        _t(ui, key, n=n)
        for n, key in ((n_ts, "clean_ts"), (n_meta, "clean_meta"), (n_sec, "clean_sections"),
                       (n_credit, "clean_credits"), (n_junk, "clean_junk"))
        if n
    ]
    return "\n".join(out), counts + report


def read_lyrics_file(path: str | Path) -> str:
    """업로드한 .txt/.lrc 파일을 인코딩을 추정해 읽는다.

    BOM → UTF-8 → charset_normalizer(requests 의존성으로 함께 설치됨) 추정 순서.
    Shift_JIS(일본), GBK/GB18030(중국 본토), Big5(대만·홍콩), CP949(한국) 파일을 대상으로 한다.
    """
    data = Path(path).read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        if best is not None:
            return str(best)
    except ImportError:
        pass
    return data.decode("cp949", errors="replace")
