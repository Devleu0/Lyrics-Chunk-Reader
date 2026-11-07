import pytest

from lyrics_tool.core import Translator
from lyrics_tool.reading import DICT_INTL, DICT_NAVER, DICT_OFF, available, dict_url, pieces, ruby_html, ruby_text
from lyrics_tool.render import MODE_BOTH, MODE_TARGET, UNIT_LINE, ViewOptions, to_html, to_markdown, to_print_html

from test_core import FakeBackend

needs_ja = pytest.mark.skipif(not available("ja"), reason="fugashi/unidic-lite 미설치")
needs_zh = pytest.mark.skipif(not available("zh"), reason="pypinyin 미설치")


@needs_ja
def test_japanese_ruby_skips_okurigana():
    assert pieces("君を待ってる", "ja") == (("君", "きみ"), ("を", ""), ("待", "ま"), ("ってる", ""))
    assert pieces("引き出し", "ja") == (("引", "ひ"), ("き", ""), ("出", "だ"), ("し", ""))
    assert ruby_html("Hi 漢字", "ja") == "Hi <ruby>漢字<rt>かんじ</rt></ruby>"
    assert ruby_text("君を待って", "ja") == "君(きみ)を待(ま)って"


@needs_zh
def test_chinese_pinyin_per_character():
    assert pieces("我爱你", "zh") == (("我", "wǒ"), ("爱", "ài"), ("你", "nǐ"))
    assert ruby_text("你好 吗", "zh") == "你好 吗 (nǐ hǎo ma)"
    assert ruby_text("重来", "zh") == "重来 (chóng lái)"


def test_no_reading_for_english():
    assert pieces("I'm here", "en") == (("I'm here", ""),)
    assert ruby_html("<b>", "en") == "&lt;b&gt;"


def test_dict_url():
    assert dict_url("「君を」", "ja", DICT_NAVER) == "https://ja.dict.naver.com/#/search?query=%E5%90%9B%E3%82%92"
    assert dict_url("love,", "en", DICT_INTL) == "https://en.wiktionary.org/wiki/Special:Search?search=love"
    assert dict_url("a/b", "ja", DICT_INTL) == "https://jisho.org/search/a%2Fb"
    assert dict_url("...", "en", DICT_NAVER) == "" and dict_url("love", "en", DICT_OFF) == ""


def _ja_doc():
    return Translator(FakeBackend()).translate("君を 待って", "ja")


@needs_ja
def test_render_ruby_and_links():
    body = to_html(_ja_doc(), MODE_BOTH, UNIT_LINE).split("</style>")[1]
    assert ('<a class="jk-s" href="https://ja.dict.naver.com/#/search?query=%E5%90%9B%E3%82%92" target="_blank" '
            'rel="noopener noreferrer" data-tts="君を" title="Click: listen · Middle-click: dictionary">'
            '<ruby>君<rt>きみ</rt></ruby>を</a>') in body
    assert 'class="jk-wrap" data-lang="ja" data-no-voice="No voice is installed' in body
    printed = to_print_html(_ja_doc(), MODE_BOTH, UNIT_LINE, None, "t").split("</style>")[1]
    assert "data-tts" not in printed and "data-lang" not in printed and 'title="Look up in dictionary"' in printed
    korean = to_html(_ja_doc(), MODE_TARGET, UNIT_LINE).split("</style>")[1]
    assert '<span class="jk-src"><ruby>君<rt>きみ</rt></ruby>を' in korean
    assert "君(きみ)を / 待(ま)って" in to_markdown(_ja_doc(), MODE_BOTH, UNIT_LINE)


def test_render_options_off():
    opts = ViewOptions(reading=False, dictionary=DICT_OFF)
    body = to_html(_ja_doc(), MODE_BOTH, UNIT_LINE, opts).split("</style>")[1]
    assert "<ruby>" not in body and "<a " not in body and '<span class="jk-s" data-tts="君を" title="Click to listen">君を</span>' in body
    assert "君を / 待って" in to_markdown(_ja_doc(), MODE_BOTH, UNIT_LINE, opts)
