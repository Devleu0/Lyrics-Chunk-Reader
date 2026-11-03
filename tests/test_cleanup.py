from lyrics_tool.cleanup import clean_lyrics, read_lyrics_file


def test_removes_tags_credits_and_junk():
    raw = """作词：某人
作曲：某人

[Verse 1]
I walk alone
(Oh baby)
[Chorus]
Stay with me
You might also like
Stay with me 12Embed"""
    text, report = clean_lyrics(raw)
    assert text == "I walk alone\n(Oh baby)\n\nStay with me\nStay with me"
    assert any("구간 표시" in r for r in report)
    assert any("크레딧" in r for r in report)
    assert any("잔여물" in r for r in report)


def test_section_tags_in_other_languages():
    text, _ = clean_lyrics("【サビ】\n君に会いたい\n(副歌)\n我想你\n[Bridge]\nhey")
    assert text == "君に会いたい\n\n我想你\n\nhey"
    text, _ = clean_lyrics("후렴:\n사랑해\n좋아해")
    assert text == "사랑해\n좋아해"  # 원문이 한국어면 한국어 줄을 지우지 않음


def test_lrc_timestamps_meta_and_stanza_breaks():
    raw = "\n".join(
        ["[ti:Song]", "[ar:Artist]"]
        + [f"[00:{10 + 3 * k:02d}.00]line {k}" for k in range(4)]
        + [f"[00:{40 + 3 * k:02d}.50]next {k}" for k in range(4)]
    )
    text, report = clean_lyrics(raw)
    assert text == "line 0\nline 1\nline 2\nline 3\n\nnext 0\nnext 1\nnext 2\nnext 3"
    assert any("타임스탬프 8줄" in r for r in report)
    assert any("연 구분 1곳" in r for r in report)


def test_drops_interleaved_korean_translation():
    raw = "君に会いたい\n너를 만나고 싶어\n夜が明ける\n밤이 밝아\n今日も歌う"
    text, report = clean_lyrics(raw)
    assert text == "君に会いたい\n夜が明ける\n今日も歌う"
    assert any("한국어 번역 줄 2줄" in r for r in report)


def test_keeps_clean_lyrics_untouched():
    raw = "I miss you\n\nall night long"
    assert clean_lyrics(raw) == (raw, [])


def test_read_file_encodings(tmp_path):
    p = tmp_path / "a.lrc"
    p.write_bytes("君に会いたい".encode("shift_jis"))
    assert read_lyrics_file(p) == "君に会いたい"
    zh = "夜空中最亮的星\n能否听清\n那仰望的人\n心底的孤独和叹息"
    p.write_bytes(zh.encode("gb18030"))
    assert read_lyrics_file(p) == zh
    p.write_bytes("﻿hello".encode("utf-8"))
    assert read_lyrics_file(p) == "hello"
