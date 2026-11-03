from lyrics_tool.core import Translator
from lyrics_tool.render import (
    MODE_BOTH, MODE_TARGET, MODE_SOURCE, UNIT_LINE, UNIT_SENTENCE, ViewOptions, to_html, to_markdown,
    to_print_html,
)

from test_core import FakeBackend


def _doc():
    return Translator(FakeBackend(group=True)).translate("I wait >\nyou\n\nbye", "en")


def test_both_mode_shows_chunks_and_korean():
    doc = _doc()
    md = to_markdown(doc, MODE_BOTH, UNIT_LINE)
    assert "I / wait / >  \n<I> / <wait> / <>>  \n→ KO I wait >" in md
    md = to_markdown(doc, MODE_BOTH, UNIT_SENTENCE)
    assert "I / wait / >  \n<I> / <wait> / <>>  \nyou  \n<you>  \n→ S[I wait > you]" in md
    html = to_html(doc, MODE_BOTH, UNIT_SENTENCE)
    assert html.count('class="jk-chunk"') == 5 and "S[I wait &gt; you]" in html


def test_source_mode_has_no_korean_line():
    assert "jk-ko" not in to_html(_doc(), MODE_SOURCE).split("</style>")[1]


def test_view_options():
    doc = _doc()
    html = to_html(doc, MODE_BOTH, UNIT_LINE, ViewOptions(font_size=20, show_numbers=False, hide_translation=True))
    assert "--jk-fs:20px" in html and "jk-nonum" in html and "jk-hide" in html
    assert 'class="jk-t" tabindex="0"' in html and 'class="jk-tr" tabindex="0"' in html
    plain = to_html(doc, MODE_BOTH, UNIT_LINE)
    assert "tabindex" not in plain and "jk-nonum" not in plain.split("</style>")[1]


def test_print_html_is_standalone():
    page = to_print_html(_doc(), MODE_TARGET, UNIT_SENTENCE, None, "<제목>", "영어 · qwen")
    assert page.startswith("<!doctype html>") and "&lt;제목&gt;" in page
    assert "@media print" in page and "→ S[I wait &gt; you]" in page
