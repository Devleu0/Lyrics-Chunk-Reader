import pytest

from lyrics_tool.cache import Cache
from lyrics_tool.core import Chunk, Translator, apply_edit, chunks_to_text, sentence_of, text_to_chunks

from test_core import FakeBackend


def test_retranslate_only_target_sentence():
    doc = Translator(FakeBackend(group=True)).translate("a >\nb\nc", "en")
    other = FakeBackend(group=True, tag="NEW")
    Translator(other).retranslate(doc, 2)  # 1~2줄이 한 문장 → 두 줄 함께 재번역
    assert other.calls == [["a >", "b"]]
    lines = doc.lines()
    assert [l.ko for l in lines] == ["NEW a >", "NEW b", "KO c"]
    s = sentence_of(doc, 1)
    assert (s.start, s.end) == (1, 2)
    assert "[앞뒤 문맥" in other.prompts[0] and "c" in other.prompts[0]


def test_retranslate_applies_to_repeated_stanza_and_cache():
    cache = Cache(":memory:")
    doc = Translator(FakeBackend(), cache=cache).translate("x\n\nx", "en")
    Translator(FakeBackend(tag="FIX"), cache=cache).retranslate(doc, 3)
    assert [l.ko for l in doc.lines() if not l.blank] == ["FIX x", "FIX x"]
    again = Translator(FakeBackend(), cache=cache).prepare("x\n\nx", "en")
    assert again.lines()[0].ko == "FIX x"


def test_retry_failed_fixes_errors():
    t_bad = Translator(FakeBackend(refuse_words=("B",)), max_attempts=1)
    doc = t_bad.translate("A\nB\n\nC", "en")
    assert doc.lines()[1].error
    fb = FakeBackend()
    list(Translator(fb).retry_failed(doc))
    assert fb.calls == [["B"]]
    assert all(l.ok for l in doc.lines())


def test_apply_edit_updates_line_sentence_and_cache():
    cache = Cache(":memory:")
    doc = Translator(FakeBackend(group=True), cache=cache).translate("p >\nq", "en")
    apply_edit(doc, 2, [Chunk("q", "큐")], "줄 수정", "문장 수정", cache=cache)
    assert doc.lines()[1].ko == "줄 수정"
    assert sentence_of(doc, 1).ko == "문장 수정"
    again = Translator(FakeBackend(group=True), cache=cache).prepare("p >\nq", "en")
    assert sentence_of(again, 2).ko == "문장 수정"


def test_apply_edit_validation():
    doc = Translator(FakeBackend()).prepare("z", "en")
    with pytest.raises(ValueError):
        apply_edit(doc, 1, [Chunk("z", "z")], "k")  # 아직 번역 전
    with pytest.raises(KeyError):
        doc.locate(5)


def test_chunk_text_roundtrip():
    chunks = [Chunk("君に", "너에게"), Chunk("会いたい", "만나고 싶어")]
    text = chunks_to_text(chunks)
    assert text == "君に | 너에게\n会いたい | 만나고 싶어"
    assert text_to_chunks(text + "\n\n") == chunks
