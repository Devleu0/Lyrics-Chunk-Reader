import pytest

from lyrics_tool.cache import Cache
from lyrics_tool.cleanup import clean_lyrics
from lyrics_tool.core import Translator, build_user_prompt
from lyrics_tool.i18n import S, pick_ui, t
from lyrics_tool.langs import LANGS, detect_language, lang_name

from test_core import FakeBackend


@pytest.mark.parametrize("text, lang", [
    ("君に会いたい", "ja"),
    ("我想见你\n在这个夜晚", "zh"),
    ("너를 기다리고 있어\nall night long", "ko"),  # 한국어 가사에 영어 한 줄
    ("I miss you every night", "en"),
    ("Te quiero, mi amor, y no puedo vivir sin ti", "es"),
    ("Je ne veux pas te perdre, mon amour", "fr"),
    ("Ich liebe dich und du bist nicht hier", "de"),
    ("Eu não sei viver sem você, meu amor", "pt"),
    ("Non ho paura, io sono con te", "it"),
    ("Я люблю тебя", "ru"),
    ("Em yêu anh nhiều lắm, đừng đi", "vi"),
    ("ฉันรักเธอ", "th"),
    ("Aku cinta kamu dan tak akan pergi", "id"),
    ("la la\nhey yo", "en"),  # 우연히 겹치는 한 단어로 다른 언어가 되지 않음
])
def test_detect_language(text, lang):
    assert detect_language(text) == lang


def test_prompt_uses_target_language_and_chunk_guide():
    p = build_user_prompt([(1, "君に会いたい")], "ja", target="en")
    assert "Source language: Japanese" in p and "Target language: English" in p
    assert "bunsetsu" in p and "[INPUT]\n1: 君に会いたい" in p
    assert "sense groups" in build_user_prompt([(1, "hola")], "es", target="ko")


def test_target_language_is_part_of_cache_key():
    cache = Cache(":memory:")
    fb = FakeBackend()
    Translator(fb, cache=cache, target="ko").translate("hello", "en")
    doc = Translator(fb, cache=cache, target="ja").translate("hello", "en")
    assert len(fb.calls) == 2 and doc.target == "ja"
    assert "Target language: Japanese" in fb.prompts[1]


def test_messages_follow_ui_language():
    doc = Translator(FakeBackend(garbage=True), max_attempts=1, ui="ko").translate("a b", "en")
    assert "거부" in doc.lines()[0].error
    _, report = clean_lyrics("[Chorus]\nhey", ui="en")
    assert report == ["1 section labels (→ stanza breaks)"]


def test_korean_lines_kept_unless_asked():
    raw = "君に会いたい\n너를 만나고 싶어\n夜が明ける\n밤이 밝아\n今日も歌う"
    assert clean_lyrics(raw, drop_hangul=False)[0] == raw


def test_i18n_tables_complete():
    for key, (en, ko) in S.items():
        assert en and ko, key
    assert t("ko", "n_lines", n=3) == "3줄" and t("en", "n_lines", n=3) == "3 lines"
    assert t("en", "no_such_key") == "no_such_key"
    assert pick_ui("ko-KR,ko;q=0.9,en;q=0.8") == "ko" and pick_ui("en-US") == "en" and pick_ui(None) == "en"
    assert lang_name("ja", "ko") == "일본어" and lang_name("ja", "en") == "Japanese"
    assert all(len(v) == 2 for v in LANGS.values())
