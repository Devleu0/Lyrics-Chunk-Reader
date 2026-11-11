import io
import zipfile

from lyrics_tool import speech
from lyrics_tool.core import Translator

from test_core import FakeBackend

# MPEG-2 Layer III, 48 kbps, 24 kHz, 모노 — edge-tts가 주는 형식. 한 프레임 144바이트 = 0.024초
HEAD = b"\xff\xf3\x64\xc4"


def _mp3(n_frames: int) -> bytes:
    return (HEAD + b"\x11" * 140) * n_frames


def test_frames_and_silence():
    data = b"ID3\x03\x00\x00\x00\x00\x00\x02xx" + _mp3(50)  # ID3 태그는 건너뛴다
    assert len(speech.frames(data)) == 50 and abs(speech.duration(data) - 1.2) < 1e-6
    quiet = speech.silence(data, 0.48)
    assert len(quiet) == 20 * 144 and quiet[:4] == HEAD and set(quiet[4:144]) == {0}


def test_build_song_gaps_and_timings():
    doc = Translator(FakeBackend()).prepare("a\nb\n\nc", "en")
    clips = {1: _mp3(10), 2: _mp3(20), 4: _mp3(10)}  # 0.24초, 0.48초, 0.24초
    song, tm = speech.build_song(doc, clips, speech.GAP_ECHO)
    assert [x.line for x in tm] == [1, 2, 4]
    assert abs(tm[0].start - 0.3) < 0.03 and abs(tm[0].end - 0.54) < 0.03
    # 따라 말하기: 줄 길이 + 0.5초 쉼, 연이 바뀌면 0.8초 더
    assert abs(tm[1].start - (0.54 + 0.24 + 0.5)) < 0.05
    assert abs(tm[2].start - (tm[1].end + 0.48 + 0.5 + speech.STANZA_EXTRA)) < 0.05
    assert abs(speech.duration(song) - (tm[2].end + 0.24 + 0.5)) < 0.05


def test_lines_zip_names_and_voices():
    doc = Translator(FakeBackend()).prepare("Hello world\n\nbye/now", "en")
    names = zipfile.ZipFile(io.BytesIO(speech.lines_zip(doc, {1: _mp3(1), 3: _mp3(1)}))).namelist()
    assert names == ["01_Hello_world.mp3", "03_bye_now.mp3"]
    assert speech.voice_for("ja") == "ja-JP-NanamiNeural" and speech.voice_for("zh", speech.MALE) == "zh-CN-YunxiNeural"
    assert speech.voice_for("xx") == "en-US-AvaNeural"
    assert speech.rate_str(0.8) == "-20%" and speech.rate_str(1.0) == "+0%" and speech.rate_str(1.3) == "+30%"
