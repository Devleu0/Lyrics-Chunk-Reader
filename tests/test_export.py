import json
import zipfile

from lyrics_tool.export import FMT_JSON, FMT_MD, FMT_MOBILE, FMT_PRINT, song_files, write_bundle, write_song
from lyrics_tool.render import MODE_BOTH, MODE_SOURCE, UNIT_SENTENCE, ViewOptions, to_image_html, to_mobile_html

from test_core import FakeBackend
from lyrics_tool.core import Translator


def _doc(title, text="I wait >\nyou\n\nbye"):
    doc = Translator(FakeBackend(group=True)).translate(text, "en")
    doc.title = title
    return doc


def test_song_files_has_every_format():
    files = song_files(_doc("A/B"), MODE_BOTH, UNIT_SENTENCE, ViewOptions(ui="ko"))
    assert sorted(files) == ["A_B_both-sentence.md", "A_B_both-sentence_print.html", "A_B_data.json",
                             "A_B_mobile.html"]
    assert json.loads(files["A_B_data.json"])["lang"] == "en"


def test_write_song_mobile_first(tmp_path):
    paths = write_song(_doc("x"), MODE_SOURCE, UNIT_SENTENCE, ViewOptions(), tmp_path)
    assert paths[0].endswith("x_mobile.html") and len(paths) == 4


def test_mobile_html_holds_all_modes_and_toc():
    docs = [_doc("One"), _doc("Two", "bye")]
    page = to_mobile_html([(d, "meta") for d in docs], MODE_BOTH, UNIT_SENTENCE, ViewOptions(ui="ko"), "Book")
    assert page.startswith("<!doctype html>") and 'name="viewport"' in page and 'data-mode="both"' in page
    # 여러 곡: 한 번에 한 곡(처음은 1번), ⋮ 서랍의 곡 목록, 곡 끝의 이전·다음
    assert 'class="m-many"' in page and page.count('class="m-song') == 2 and 'class="m-song m-cur" id="song-1"' in page
    assert 'id="m-drawer"' in page and 'data-act="menu"' in page and 'href="#song-2"' in page
    assert '<div class="m-nav"><span class="m-gap"></span><a class="m-next" href="#song-2">' in page
    assert '<a href="#song-1"><small>‹ 이전 곡</small>One</a><span class="m-gap"></span>' in page
    assert 'data-fs="15"' in page
    for m in ("source", "target", "both"):
        assert page.count(f'class="m-mode" data-mode="{m}"') == 2
    assert "S[I wait &gt; you]" in page  # 문장 단위 직역
    assert "data-tts=" in page and "speechSynthesis" in page and "prefers-color-scheme: dark" in page
    single = to_mobile_html([(docs[0], "m")], MODE_SOURCE, UNIT_SENTENCE, None, "One")
    markup = single.split("<script>")[0]  # 곡이 하나면 서랍·⋮·이전·다음이 없다
    assert all(k not in markup for k in ('id="m-drawer"', 'data-act="menu"', 'class="m-nav"', 'class="m-many"'))


def test_image_html_is_self_contained():
    frag = to_image_html(_doc("<T>"), MODE_BOTH, UNIT_SENTENCE, ViewOptions(hide_translation=True), "<T>", "en",
                         width="wide", dark=True)
    assert frag.startswith('<div class="jk-img"><style>') and "width: 820px" in frag and "#161616" in frag
    body = frag.split("</style>")[1]
    assert "&lt;T&gt;" in body and "<a " not in body and "data-tts" not in body and "jk-hide" not in body


def test_bundle_zip_and_book(tmp_path):
    docs = [_doc("Same"), _doc("Same", "bye")]
    zip_path, book = write_bundle(docs, MODE_BOTH, UNIT_SENTENCE, ViewOptions(), [FMT_MD, FMT_MOBILE, FMT_JSON],
                                  tmp_path, "My book")
    assert book.endswith("My_book_mobile.html") and zip_path.endswith("My_book.zip")
    names = sorted(zipfile.ZipFile(zip_path).namelist())
    assert names == ["1_Same/Same_both-sentence.md", "1_Same/Same_data.json", "2_Same/Same_both-sentence.md",
                     "2_Same/Same_data.json", "My_book_mobile.html"]  # 같은 제목도 폴더로 나뉜다


def test_bundle_mobile_only_has_no_zip(tmp_path):
    paths = write_bundle([_doc("a")], MODE_SOURCE, UNIT_SENTENCE, ViewOptions(), [FMT_MOBILE], tmp_path, "b")
    assert len(paths) == 1 and paths[0].endswith("b_mobile.html")
    assert write_bundle([], MODE_SOURCE, UNIT_SENTENCE, ViewOptions(), [FMT_PRINT], tmp_path, "b") == []
