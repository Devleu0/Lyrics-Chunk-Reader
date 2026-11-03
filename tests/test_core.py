import json

import pytest

from lyrics_tool.backends import Backend, BackendError, RefusalError
from lyrics_tool.cache import Cache
from lyrics_tool.core import (
    SegLine, Chunk, Translator, detect_language, normalize_sentences, parse_response, split_segments,
)
from lyrics_tool.render import MODE_KOREAN, MODE_SOURCE, UNIT_LINE, UNIT_SENTENCE, to_html, to_markdown


class FakeBackend(Backend):
    """프롬프트의 [입력] 줄을 읽어 규칙대로 응답하는 가짜 엔진.

    group=True 이면 '>'로 끝나는 줄을 다음 줄과 한 문장으로 묶는다.
    """

    def __init__(self, refuse_words=(), garbage=False, raise_backend=False, group=False, tag="KO"):
        super().__init__(model="fake")
        self.refuse_words, self.garbage, self.raise_backend = refuse_words, garbage, raise_backend
        self.group, self.tag = group, tag
        self.calls, self.prompts = [], []

    def chat(self, system, user):
        self.prompts.append(user)
        body = user.split("[입력]\n", 1)[1].split("\n\n[참고]")[0]
        lines = [(int(a), b) for a, b in (l.split(": ", 1) for l in body.splitlines())]
        self.calls.append([t for _, t in lines])
        if self.raise_backend:
            raise BackendError("down")
        if any(w in t for _, t in lines for w in self.refuse_words):
            raise RefusalError("blocked")
        if self.garbage:
            return "I'm sorry, I can't help with that."
        sents, k = [], 0
        while k < len(lines):
            i, t = lines[k]
            if self.group and t.endswith(">") and k + 1 < len(lines):
                sents.append({"from": i, "to": lines[k + 1][0], "ko": f"S[{t} {lines[k + 1][1]}]"})
                k += 2
            else:
                sents.append({"from": i, "to": i, "ko": "ignored"})
                k += 1
        return json.dumps({
            "lines": [{"i": i, "chunks": [{"s": w, "k": f"<{w}>"} for w in t.split()],
                       "ko": f"{self.tag} {t}"} for i, t in lines],
            "sentences": sents,
        }, ensure_ascii=False)


def test_detect_language():
    assert detect_language("君に会いたい") == "ja"
    assert detect_language("我想见你") == "zh"
    assert detect_language("I miss you") == "en"


def test_split_segments_by_stanza_and_size():
    src = ["a", "b", "c", "", "d", "", "", "e"]
    assert split_segments(src, 2) == [[1, 2], [3], [5], [8]]


def test_parse_handles_code_fence_and_drops_bad_lines():
    text = "```json\n" + json.dumps({"lines": [
        {"i": 1, "chunks": [{"s": "I", "k": "나"}, {"s": "run", "k": "달린다"}], "ko": "나는 달린다"},
        {"i": 2, "chunks": [{"s": "totally different", "k": "x"}], "ko": "x"},  # 원문 불일치
        {"i": 3, "chunks": [], "ko": "x"},  # 청크 없음
    ], "sentences": [{"from": 1, "to": 2, "ko": "s"}]}) + "\n```"
    lines, sents = parse_response(text, {1: "I run", 2: "we go", 3: "fly"})
    assert list(lines) == [1]
    assert sents == [(1, 2, "s")]


def test_parse_detects_refusal_text():
    with pytest.raises(RefusalError):
        parse_response("죄송하지만 저작권 때문에 도와드릴 수 없습니다.", {1: "a"})


def test_normalize_sentences_fills_gaps_and_drops_invalid():
    ok = SegLine([Chunk("a", "b")], "ko")
    bad = SegLine(error="x")
    lines = [ok, ok, bad, ok, ok]
    raw = [(1, 2, "S12"), (2, 3, "overlap"), (3, 4, "has failed line"), (5, 9, "out of range")]
    got = normalize_sentences(5, lines, raw)
    assert got == [(0, 1, "S12"), (2, 2, ""), (3, 3, "ko"), (4, 4, "ko")]


def test_translate_preserves_blanks_and_dedups_repeated_stanza():
    fb = FakeBackend()
    doc = Translator(fb, batch_size=10).translate("la la\nhey\n\nyo\n\nla la\nhey", "auto")
    assert doc.lang == "en"
    lines = doc.lines()
    assert [r.blank for r in lines] == [False, False, True, False, True, False, False]
    assert len(fb.calls) == 2  # 반복되는 연은 한 번만
    assert lines[5].ko == lines[0].ko == "KO la la"


def test_sentence_grouping():
    doc = Translator(FakeBackend(group=True)).translate("I wait >\nfor you\nalone", "en")
    sents = [(s.start, s.end, s.ko) for s in doc.sentences()]
    assert sents == [(1, 2, "S[I wait > for you]"), (3, 3, "KO alone")]


def test_neighbor_context_is_sent():
    fb = FakeBackend()
    Translator(fb, batch_size=2).translate("a1\na2\na3", "en")
    assert "[앞뒤 문맥" in fb.prompts[1] and "a2" in fb.prompts[1]


def test_batch_refusal_falls_back_to_single_lines():
    fb = FakeBackend(refuse_words=("BAD",))
    doc = Translator(fb, batch_size=5, max_attempts=2).translate("good one\nBAD line\ngood two", "en")
    lines = doc.lines()
    assert lines[0].ok and lines[2].ok
    assert lines[1].error and not lines[1].ok
    assert fb.calls[0] == ["good one", "BAD line", "good two"]
    assert fb.calls.count(["BAD line"]) == 2  # max_attempts 만큼 재시도


def test_garbage_response_marks_errors():
    doc = Translator(FakeBackend(garbage=True), max_attempts=1).translate("a b", "en")
    assert "거부" in doc.lines()[0].error


def test_backend_error_propagates():
    with pytest.raises(BackendError):
        Translator(FakeBackend(raise_backend=True)).translate("a", "en")


def test_run_yields_progressively():
    t = Translator(FakeBackend())
    doc = t.prepare("a\n\nb\n\nc", "en")
    assert all(r.pending for r in doc.lines() if not r.blank)
    steps = [d.progress() for d in t.run(doc)]
    assert steps == [(1, 3), (2, 3), (3, 3)]


def test_cache_hit_skips_backend_and_skips_failed():
    cache = Cache(":memory:")
    fb = FakeBackend(refuse_words=("BAD",))
    Translator(fb, cache=cache, max_attempts=1).translate("ok\n\nBAD", "en")
    assert len(cache) == 1  # 실패한 구간은 저장 안 함

    fb2 = FakeBackend()
    doc = Translator(fb2, cache=cache).translate("ok\n\nBAD", "en")
    assert fb2.calls == [["BAD"]]  # 캐시 적중한 구간은 호출 없음
    assert doc.lines()[0].ko == "KO ok"


def test_cache_key_depends_on_model():
    cache = Cache(":memory:")
    Translator(FakeBackend(), cache=cache).translate("x", "en")
    other = FakeBackend()
    other.model = "other"
    Translator(other, cache=cache).translate("x", "en")
    assert len(other.calls) == 1


def test_render_modes_and_units():
    doc = Translator(FakeBackend(group=True)).translate("I <3 >\nyou\n\nbye", "en")
    src_md = to_markdown(doc, MODE_SOURCE)
    assert "I / <3 / >" in src_md and "<I> / <<3> / <>>" in src_md
    assert "→ KO you" in to_markdown(doc, MODE_KOREAN, UNIT_LINE)
    sent_md = to_markdown(doc, MODE_KOREAN, UNIT_SENTENCE)
    assert "I <3 >  \nyou  \n→ S[I <3 > you]" in sent_md and "→ KO bye" in sent_md
    assert "&lt;3" in to_html(doc, MODE_SOURCE)
    assert "jk-sent" in to_html(doc, MODE_KOREAN, UNIT_SENTENCE)


def test_bisect_keeps_sentence_groups_when_one_line_refused():
    fb = FakeBackend(group=True, refuse_words=("BAD",))
    doc = Translator(fb, max_attempts=1).translate("a >\nb\nc\nBAD", "en")
    assert ["a >", "b"] in fb.calls  # 거부된 묶음을 반으로 나눠 다시 보냄
    s = [(x.start, x.end) for x in doc.sentences()]
    assert (1, 2) in s
    assert doc.lines()[3].error and doc.lines()[2].ok


def test_regroup_restores_sentence_cut_by_bisect():
    fb = FakeBackend(group=True, refuse_words=("BAD",))
    doc = Translator(fb, max_attempts=1).translate("a >\nb\nBAD", "en")
    # [a >] | [b, BAD] 로 나뉘어 끊겼던 1~2줄 문장을, 거부 줄을 뺀 재요청으로 되살림
    assert fb.calls[-1] == ["a >", "b"]
    assert "BAD" not in fb.prompts[-1].split("[입력]")[0]  # 거부 줄은 문맥에서도 제외
    s = [(x.start, x.end, x.ko) for x in doc.sentences()]
    assert (1, 2, "S[a > b]") in s


def test_no_regroup_when_batch_succeeds():
    fb = FakeBackend(group=True)
    Translator(fb).translate("a >\nb\nc", "en")
    assert len(fb.calls) == 1
