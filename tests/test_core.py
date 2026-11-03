import json

import pytest

from lyrics_tool.backends import Backend, BackendError, RefusalError
from lyrics_tool.core import Translator, detect_language, parse_response
from lyrics_tool.render import MODE_KOREAN, MODE_SOURCE, to_html, to_markdown


def _gloss(lines):
    return json.dumps(
        {"lines": [{"i": i, "chunks": [{"s": w, "k": f"<{w}>"} for w in t.split()], "ko": "KO " + t}
                   for i, t in lines]},
        ensure_ascii=False,
    )


class FakeBackend(Backend):
    """프롬프트의 [입력] 줄을 읽어 규칙대로 응답하는 가짜 엔진."""

    def __init__(self, refuse_words=(), garbage=False, raise_backend=False):
        super().__init__(model="fake")
        self.refuse_words = refuse_words
        self.garbage = garbage
        self.raise_backend = raise_backend
        self.calls = []

    def chat(self, system, user):
        body = user.split("[입력]\n", 1)[1].split("\n\n[참고]")[0]
        lines = [(int(a), b) for a, b in (l.split(": ", 1) for l in body.splitlines())]
        self.calls.append([i for i, _ in lines])
        if self.raise_backend:
            raise BackendError("down")
        if any(w in t for _, t in lines for w in self.refuse_words):
            raise RefusalError("blocked")
        if self.garbage:
            return "I'm sorry, I can't help with that."
        return _gloss(lines)


def test_detect_language():
    assert detect_language("君に会いたい") == "ja"
    assert detect_language("我想见你") == "zh"
    assert detect_language("I miss you") == "en"


def test_parse_handles_code_fence_and_drops_bad_lines():
    text = "```json\n" + json.dumps({"lines": [
        {"i": 1, "chunks": [{"s": "I", "k": "나"}, {"s": "run", "k": "달린다"}], "ko": "나는 달린다"},
        {"i": 2, "chunks": [{"s": "totally different", "k": "x"}], "ko": "x"},  # 원문 불일치
        {"i": 3, "chunks": [], "ko": "x"},  # 청크 없음
    ]}) + "\n```"
    got = parse_response(text, {1: "I run", 2: "we go", 3: "fly"})
    assert list(got) == [1]


def test_parse_detects_refusal_text():
    with pytest.raises(RefusalError):
        parse_response("죄송하지만 저작권 때문에 도와드릴 수 없습니다.", {1: "a"})


def test_translate_preserves_blanks_and_dedups_chorus():
    fb = FakeBackend()
    results, lang = Translator(fb, batch_size=10).translate("la la\n\nhey you\nla la", "auto")
    assert lang == "en"
    assert [r.blank for r in results] == [False, True, False, False]
    assert fb.calls == [[1, 3]]  # 빈 줄 제외, 반복 줄 1회만
    assert results[3].ko == results[0].ko == "KO la la"


def test_batch_refusal_falls_back_to_single_lines():
    fb = FakeBackend(refuse_words=("BAD",))
    results, _ = Translator(fb, batch_size=5, max_attempts=2).translate("good one\nBAD line\ngood two", "en")
    assert results[0].ok and results[2].ok
    assert results[1].error and not results[1].ok
    assert fb.calls[0] == [1, 2, 3]
    assert [1] in fb.calls and [3] in fb.calls
    assert fb.calls.count([2]) == 2  # max_attempts 만큼 재시도


def test_garbage_response_marks_errors():
    results, _ = Translator(FakeBackend(garbage=True), max_attempts=1).translate("a b", "en")
    assert "거부" in results[0].error


def test_backend_error_propagates():
    with pytest.raises(BackendError):
        Translator(FakeBackend(raise_backend=True)).translate("a", "en")


def test_render_both_modes():
    results, _ = Translator(FakeBackend()).translate("I <3 you", "en")
    src_md = to_markdown(results, MODE_SOURCE)
    assert "I / <3 / you" in src_md and "<I> / <<3> / <you>" in src_md
    assert "→ KO I <3 you" in to_markdown(results, MODE_KOREAN)
    assert "&lt;3" in to_html(results, MODE_SOURCE)  # HTML 이스케이프
