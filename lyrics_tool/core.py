"""직독직해 번역 코어.

흐름
  가사 → 줄 분리 → 연(빈 줄로 구분) 단위 구간(Segment)으로 나눔
       → 구간마다 LLM 1회 호출(JSON) → 검증 → 빠진 줄은 1줄씩(문맥 포함) 재시도
       → 구간 결과(SegResult)를 캐시에 저장

한 번의 호출로 세 가지를 함께 받는다. 그래서 보기 방식을 바꿔도 재호출하지 않는다.
  - 줄별 chunks : 원문 어순 의미 단위(s) + 번역 언어로 단 뜻(t)
  - 줄별 tr     : 그 줄을 번역 언어 어순으로 옮긴 직역
  - sentences   : 여러 줄에 걸친 문장을 묶은 범위 + 묶음 전체의 직역
원문·번역 언어는 langs.LANGS의 주요 언어 중에서 고른다.

구간을 연 경계에서 자르므로 한 문장이 배치 경계에서 잘리는 일이 줄어들고,
같은 연(후렴)이 반복되면 같은 캐시 키로 한 번만 번역한다.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Iterator

from .backends import Backend, BackendError, RefusalError
from .cache import Cache, make_key
from .i18n import t as _t
from .langs import LANGS, detect_language

PROMPT_VERSION = 3  # 3: 영어 프롬프트 + 번역 언어 선택, 필드 이름 t/tr

# ================================================================ 데이터 모델


@dataclass
class Chunk:
    s: str  # 원문 조각
    t: str  # 번역 언어로 단 뜻


@dataclass
class SegLine:
    chunks: list[Chunk] = field(default_factory=list)
    tr: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.chunks) and bool(self.tr) and not self.error


@dataclass
class SegResult:
    """한 구간의 번역 결과. sentences는 구간 내 0-based 포함 범위 (start, end, tr)."""

    lines: list[SegLine]
    sentences: list[tuple[int, int, str]]

    @property
    def ok(self) -> bool:
        return all(l.ok for l in self.lines)

    def to_dict(self) -> dict:
        return {
            "lines": [asdict(l) for l in self.lines],
            "sentences": [list(s) for s in self.sentences],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SegResult":
        lines = [
            SegLine([Chunk(**c) for c in l["chunks"]], l["tr"], l.get("error", ""))
            for l in d["lines"]
        ]
        return cls(lines, [tuple(s) for s in d["sentences"]])


@dataclass
class Segment:
    key: str
    indices: list[int]  # 문서 전체 기준 1-based 줄 번호 (연속)


@dataclass
class LineResult:
    """화면 표시용 줄 (Doc에서 조립)."""

    index: int
    source: str
    chunks: list[Chunk] = field(default_factory=list)
    tr: str = ""
    error: str = ""
    pending: bool = False

    @property
    def blank(self) -> bool:
        return not self.source.strip()

    @property
    def ok(self) -> bool:
        return self.blank or (bool(self.chunks) and bool(self.tr) and not self.error)


@dataclass
class Sentence:
    start: int  # 1-based, 포함
    end: int
    tr: str
    error: str = ""
    pending: bool = False


class LineNotFound(KeyError):
    """번역 대상이 아닌 줄(빈 줄이거나 범위 밖). args[0] = 줄 번호."""


class EditError(ValueError):
    """수정할 수 없음. args[0] = i18n 키 (not_translated / need_chunks)."""


@dataclass
class Doc:
    lang: str  # 원문 언어
    sources: list[str]  # 0번 = 1번 줄
    segments: list[Segment]
    results: dict[str, SegResult] = field(default_factory=dict)
    title: str = ""
    target: str = "ko"  # 번역 언어

    # ---- 조회
    def locate(self, line_no: int) -> tuple[Segment, int]:
        for seg in self.segments:
            if line_no in seg.indices:
                return seg, seg.indices.index(line_no)
        raise LineNotFound(line_no)

    def pending_keys(self) -> list[str]:
        seen, out = set(), []
        for seg in self.segments:
            if seg.key not in self.results and seg.key not in seen:
                seen.add(seg.key)
                out.append(seg.key)
        return out

    def texts(self, seg: Segment) -> list[str]:
        return [self.sources[i - 1] for i in seg.indices]

    # ---- 조립
    def lines(self) -> list[LineResult]:
        out = [LineResult(index=n + 1, source=s) for n, s in enumerate(self.sources)]
        for seg in self.segments:
            res = self.results.get(seg.key)
            for pos, i in enumerate(seg.indices):
                r = out[i - 1]
                if res is None:
                    r.pending = True
                else:
                    sl = res.lines[pos]
                    r.chunks, r.tr, r.error = list(sl.chunks), sl.tr, sl.error
        return out

    def sentences(self) -> list[Sentence]:
        out: list[Sentence] = []
        for seg in self.segments:
            res = self.results.get(seg.key)
            if res is None:
                out += [Sentence(i, i, "", pending=True) for i in seg.indices]
                continue
            for a, b, tr in res.sentences:
                err = next((res.lines[p].error for p in range(a, b + 1) if res.lines[p].error), "")
                out.append(Sentence(seg.indices[a], seg.indices[b], tr, error=err))
        return sorted(out, key=lambda s: s.start)

    def progress(self) -> tuple[int, int]:
        keys = {s.key for s in self.segments}
        return len(keys & self.results.keys()), len(keys)

    @property
    def complete(self) -> bool:
        """모든 구간이 번역됐고 실패한 줄이 없음 — 히스토리에 남길 수 있는 상태."""
        return not self.pending_keys() and all(r.ok for r in self.lines())

    def dump(self) -> dict:
        """다시 번역하지 않고 그대로 되살릴 수 있는 전체 상태 (히스토리 파일용)."""
        return {
            "lang": self.lang,
            "target": self.target,
            "title": self.title,
            "sources": self.sources,
            "segments": [{"key": s.key, "indices": s.indices} for s in self.segments],
            "results": {k: r.to_dict() for k, r in self.results.items()},
        }

    @classmethod
    def restore(cls, d: dict) -> "Doc":
        return cls(
            lang=d["lang"],
            sources=list(d["sources"]),
            segments=[Segment(s["key"], list(s["indices"])) for s in d["segments"]],
            results={k: SegResult.from_dict(r) for k, r in d["results"].items()},
            title=d.get("title", ""),
            target=d.get("target", "ko"),
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "lang": self.lang,
                "target": self.target,
                "lines": [asdict(l) for l in self.lines()],
                "sentences": [asdict(s) for s in self.sentences()],
            },
            ensure_ascii=False,
            indent=2,
        )


# ================================================================ 프롬프트

_CHUNK_GUIDE = {
    "ja": "Split Japanese by bunsetsu (文節): a content word plus the particles/auxiliaries that follow it. "
          "e.g. 君に / 会いたくて. Carry the nuance of particles (に·を·は·が·も) into the gloss.",
    "zh": "Split Chinese into meaning units (subject phrase, verb phrase, object phrase, adverbial, complement). "
          "e.g. 我想 / 见到你 / 在这个夜晚. Keep function words such as 了·过·着·得 with the preceding word "
          "and reflect their meaning.",
    "ko": "Split Korean by eojeol (space-separated units): a content word plus its particles and endings. "
          "e.g. 너를 / 기다리고 있어. Reflect particles and verb endings in the gloss.",
    "en": "Split English into sense groups: subject / verb / object / prepositional phrase / clause. "
          "e.g. I've been waiting / for you / all night.",
    "ru": "Split Russian into sense groups; keep prepositions with their noun and reflect case meaning in the gloss.",
    "de": "Split German into sense groups; keep articles with nouns, and note separable prefixes and verb-final "
          "clauses in the gloss.",
    "th": "Thai has no spaces between words: split into short phrases (word groups) in the original order.",
}
_DEFAULT_GUIDE = (
    "Split into sense groups: subject / verb (with attached pronouns) / object / prepositional phrase / clause. "
    "Keep articles with their nouns."
)

SYSTEM_PROMPT = """You are a grammar-annotation assistant for language learners.
The user gives numbered lines of a text they are studying. Your job is to add study annotations: a chunk-by-chunk gloss and a literal translation.
- Do not rewrite, continue, or reproduce the text beyond the given lines. Only analyze each given line.
- No literary paraphrase: translate literally so the learner can follow the source structure.
- Output exactly one JSON object. No explanations, markdown, or apologies."""

_USER_TEMPLATE = """Source language: {src}
Target language: {tgt} (write every "t" and "tr" in {tgt})

[TASK]
1. lines — for each line
   - "chunks": split the line into meaning units in the original order and gloss each unit in {tgt}.
     "s" is the source chunk exactly as written; joining all "s" must reproduce the line (spacing may differ).
     "t" is the {tgt} meaning of that chunk alone. Never reorder chunks.
   - "tr": a literal translation of that line alone, rearranged into natural {tgt} word order. Every word must be reflected; no omissions or additions.
2. sentences — sentence groups
   - If consecutive lines form one sentence (one grammatical unit), group them with "from"–"to" and give "tr": a literal {tgt} translation of the whole group.
   - A self-contained line is a group whose "from" and "to" are equal.
   - Every line belongs to exactly one group; groups are in line order and never overlap.

[CHUNKING]
{guide}

[OUTPUT FORMAT]
{{"lines": [{{"i": line number, "chunks": [{{"s": "source chunk", "t": "gloss"}}], "tr": "line translation"}}],
 "sentences": [{{"from": first line, "to": last line, "tr": "group translation"}}]}}
Return exactly one "lines" entry for every input line number.
{context}
[INPUT]
{numbered}"""

_CONTEXT_TEMPLATE = """
[CONTEXT — surrounding lines, for meaning only; do not output them]
{context}
"""

_RETRY_NOTE = (
    "\n\n[NOTE] This is a grammar annotation that helps a learner understand sentence structure. "
    "Only the analysis is needed, not a reproduction of the text. Follow the format and answer in JSON only."
)


def _english(code: str) -> str:
    return LANGS[code][0] if code in LANGS else code


def build_user_prompt(
    lines: list[tuple[int, str]],
    lang: str,
    retry: bool = False,
    context: list[str] | None = None,
    target: str = "ko",
) -> str:
    numbered = "\n".join(f"{i}: {text}" for i, text in lines)
    ctx = _CONTEXT_TEMPLATE.format(context="\n".join(context)) if context else ""
    prompt = _USER_TEMPLATE.format(
        src=_english(lang),
        tgt=_english(target),
        guide=_CHUNK_GUIDE.get(lang, _DEFAULT_GUIDE),
        context=ctx,
        numbered=numbered,
    )
    return prompt + (_RETRY_NOTE if retry else "")


# ================================================================ 응답 파싱

_REFUSAL_HINTS = (
    "죄송", "도와드릴 수 없", "제공할 수 없", "저작권",
    "i'm sorry", "i am sorry", "i can't", "i cannot", "copyright", "unable to",
)


def _extract_json(text: str, ui: str = "en") -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    lowered = text.lower()
    if any(h in lowered for h in _REFUSAL_HINTS):
        raise RefusalError(_t(ui, "refused", text=text[:120]))
    raise ValueError(_t(ui, "json_fail", text=text[:120]))


def _norm(s: str) -> str:
    return re.sub(r"[\s　]+", "", s)


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def parse_response(
    text: str, expected: dict[int, str], ui: str = "en"
) -> tuple[dict[int, SegLine], list[tuple[int, int, str]]]:
    """유효한 줄과 (검증 전) 문장 묶음 목록을 반환한다. 빠진 줄은 호출자가 재시도한다."""
    data = _extract_json(text, ui)
    items = data.get("lines") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError(_t(ui, "no_lines"))

    lines: dict[int, SegLine] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            i = int(item.get("i"))
        except (TypeError, ValueError):
            continue
        if i not in expected or i in lines:
            continue
        chunks = [
            Chunk(s=str(c.get("s", "")).strip(), t=str(c.get("t", "")).strip())
            for c in item.get("chunks") or []
            if isinstance(c, dict) and str(c.get("s", "")).strip()
        ]
        tr = str(item.get("tr", "")).strip()
        if not chunks or not tr:
            continue
        # 조각을 이으면 원문이 되는지 확인 — 다른 줄을 끌어오거나 창작한 응답을 걸러낸다.
        if _similarity(_norm("".join(c.s for c in chunks)), _norm(expected[i])) < 0.8:
            continue
        lines[i] = SegLine(chunks, tr)

    sentences: list[tuple[int, int, str]] = []
    raw_sents = data.get("sentences") if isinstance(data, dict) else None
    for s in raw_sents or []:
        if not isinstance(s, dict):
            continue
        try:
            a, b = int(s.get("from")), int(s.get("to"))
        except (TypeError, ValueError):
            continue
        tr = str(s.get("tr", "")).strip()
        if tr:
            sentences.append((a, b, tr))
    return lines, sentences


def normalize_sentences(
    n: int, lines: list[SegLine], raw: list[tuple[int, int, str]], base: int = 1
) -> list[tuple[int, int, str]]:
    """모델이 준 묶음(base 기준 번호)을 검증해 0-based 범위로 바꾸고, 빈 곳은 한 줄짜리 묶음으로 채운다.

    범위를 벗어나거나 겹치거나, 실패한 줄을 포함한 묶음은 버린다.
    """
    taken = [False] * n
    out: list[tuple[int, int, str]] = []
    for a, b, tr in sorted(raw):
        a, b = a - base, b - base
        if not (0 <= a <= b < n) or any(taken[a : b + 1]):
            continue
        if not all(lines[p].ok for p in range(a, b + 1)):
            continue
        if a == b:
            tr = lines[a].tr  # 한 줄 묶음은 줄 직역과 같게 맞춘다
        out.append((a, b, tr))
        for p in range(a, b + 1):
            taken[p] = True
    for p in range(n):
        if not taken[p]:
            out.append((p, p, lines[p].tr))
    return sorted(out)


# ================================================================ 번역기


def split_segments(sources: list[str], max_lines: int) -> list[list[int]]:
    """빈 줄 기준 연으로 나누고, max_lines보다 긴 연은 잘라 1-based 줄 번호 묶음을 반환."""
    segs: list[list[int]] = []
    cur: list[int] = []

    def flush() -> None:
        for k in range(0, len(cur), max_lines):
            segs.append(cur[k : k + max_lines])
        cur.clear()

    for n, s in enumerate(sources, start=1):
        if s.strip():
            cur.append(n)
        else:
            flush()
    flush()
    return segs


class Translator:
    def __init__(
        self,
        backend: Backend,
        batch_size: int = 8,
        max_attempts: int = 2,
        cache: Cache | None = None,
        target: str = "ko",
        ui: str = "en",
    ):
        self.backend = backend
        self.target = target
        self.ui = ui
        self.batch_size = max(1, batch_size)
        self.max_attempts = max(1, max_attempts)
        self.cache = cache

    # ---- 키
    def segment_key(self, lang: str, texts: list[str]) -> str:
        return make_key(PROMPT_VERSION, self.backend.kind, self.backend.model, lang, self.target, texts)

    # ---- 준비 / 실행
    def prepare(self, lyrics: str, lang: str = "auto", use_cache: bool = True) -> Doc:
        sources = [l.strip() for l in lyrics.replace("\r\n", "\n").split("\n")]
        if lang == "auto":
            lang = detect_language(lyrics)
        segments = []
        for idx in split_segments(sources, self.batch_size):
            texts = [sources[i - 1] for i in idx]
            segments.append(Segment(self.segment_key(lang, texts), idx))
        doc = Doc(lang, sources, segments, target=self.target)
        if self.cache is not None and use_cache:
            for seg in segments:
                hit = self.cache.get(seg.key)
                if hit and seg.key not in doc.results:
                    doc.results[seg.key] = SegResult.from_dict(hit)
        return doc

    def run(self, doc: Doc) -> Iterator[Doc]:
        """번역 안 된 구간을 하나씩 처리하며 매번 doc을 내보낸다(점진 표시·중단용)."""
        by_key = {s.key: s for s in doc.segments}
        for key in doc.pending_keys():
            seg = by_key[key]
            texts = doc.texts(seg)
            # 앞뒤 구간 원문을 문맥으로 준다 (연이 잘린 경우 특히 유효)
            res = self.translate_lines(texts, doc.lang, context=self._neighbors(doc, seg))
            doc.results[key] = res
            self._save(key, res)
            yield doc

    def translate(self, lyrics: str, lang: str = "auto", use_cache: bool = True) -> Doc:
        doc = self.prepare(lyrics, lang, use_cache)
        for _ in self.run(doc):
            pass
        return doc

    # ---- 한 묶음 번역 (배치 → 실패 줄 단건 재시도)
    def _call(self, lines, lang, retry, context):
        raw = self.backend.chat(SYSTEM_PROMPT, build_user_prompt(lines, lang, retry, context, self.target))
        return parse_response(raw, dict(lines), self.ui)

    def translate_lines(
        self, texts: list[str], lang: str, context: list[str] | None = None
    ) -> SegResult:
        numbered = list(enumerate(texts, start=1))
        got: dict[int, SegLine] = {}
        raw_sents: list[tuple[int, int, str]] = []
        origin: dict[int, int] = {}  # 줄 → 그 줄을 받아 온 호출 번호
        call_no = [0]

        def take(lines: dict[int, SegLine]) -> None:
            call_no[0] += 1
            for i, sl in lines.items():
                got[i] = sl
                origin[i] = call_no[0]

        def bisect(part: list[tuple[int, str]], ctx: list[str] | None) -> None:
            """묶음 전체가 거부되면 반씩 나눠 다시 보낸다.

            거부되는 줄만 고립시키고 나머지 줄은 여러 줄 묶음으로 받아 문장 묶음 정보를 최대한 살린다.
            한 줄짜리는 아래 단건 재시도에 맡긴다.
            """
            if len(part) < 2:
                return
            try:
                lines, sents = self._call(part, lang, False, ctx)
            except (RefusalError, ValueError):
                mid = len(part) // 2
                for half in (part[:mid], part[mid:]):
                    rest = [t for j, t in numbered if j not in dict(half)]
                    bisect(half, rest or context)
                return
            take(lines)
            raw_sents.extend(sents)

        bisect(numbered, context)

        # 빠진 줄은 1줄씩 (작은 단위가 저작물 필터·거부를 덜 탄다). 같은 구간 원문을 문맥으로 준다.
        for i, text in numbered:
            if i in got:
                continue
            ctx = [t for j, t in numbered if j != i] or context
            last = ""
            for _ in range(self.max_attempts):
                try:
                    one, _ = self._call([(1, text)], lang, True, ctx)
                except (RefusalError, ValueError) as e:
                    last = str(e)
                    continue
                if 1 in one:
                    take({i: one[1]})
                    break
                last = _t(self.ui, "bad_format")
            else:
                got[i] = SegLine(error=last or _t(self.ui, "failed"))

        raw_sents = self._regroup(numbered, got, origin, raw_sents, lang, context)
        lines = [got[i] for i, _ in numbered]
        return SegResult(lines, normalize_sentences(len(lines), lines, raw_sents))

    def _regroup(self, numbered, got, origin, raw_sents, lang, context):
        """분할 요청 때문에 서로 다른 호출로 받은 '연속된 정상 줄'을 한 번 더 묶어 요청한다.

        거부된 줄을 빼고 보내므로 대개 통과하며, 끊겼던 문장 묶음을 되살린다.
        실패하면 기존 결과를 그대로 둔다.
        """
        bad = {i for i, _ in numbered if got[i].error}
        runs: list[list[tuple[int, str]]] = []
        cur: list[tuple[int, str]] = []
        for i, t in numbered:
            if i in bad:
                if cur:
                    runs.append(cur)
                cur = []
            else:
                cur.append((i, t))
        if cur:
            runs.append(cur)

        for run in runs:
            ids = {i for i, _ in run}
            if len(run) < 2 or len({origin.get(i) for i in ids}) < 2:
                continue
            ctx = [t for i, t in numbered if i not in ids and i not in bad] or context
            try:
                lines, sents = self._call(run, lang, True, ctx)
            except (RefusalError, ValueError):
                continue
            if set(lines) != ids:
                continue
            got.update(lines)
            raw_sents = [s for s in raw_sents if s[1] < min(ids) or s[0] > max(ids)] + sents
        return raw_sents

    # ---- 부분 재번역
    def retranslate(self, doc: Doc, line_no: int) -> None:
        """line_no가 속한 문장 묶음만 다시 번역한다(캐시 무시). 나머지 줄은 그대로 둔다.

        여러 줄 문장에 속한 줄이면 그 문장 전체를 다시 번역해 문장 직역과 줄 직역이 어긋나지 않게 한다.
        결과는 구간 캐시 키에 저장되므로 같은 연이 반복되는 곳에도 함께 반영된다.
        """
        seg, pos = doc.locate(line_no)
        texts = doc.texts(seg)
        res = doc.results.get(seg.key)
        if res is None:
            res = self.translate_lines(texts, doc.lang, self._neighbors(doc, seg))
        else:
            a, b = next((a, b) for a, b, _ in res.sentences if a <= pos <= b)
            ctx = texts[:a] + texts[b + 1 :] or self._neighbors(doc, seg)
            new = self.translate_lines(texts[a : b + 1], doc.lang, ctx)
            res = splice(res, a, b, new)
        doc.results[seg.key] = res
        self._save(seg.key, res)

    def retry_failed(self, doc: Doc) -> Iterator[Doc]:
        """번역 대기 구간과 실패한 줄을 다시 시도하며 매번 doc을 내보낸다."""
        yield from self.run(doc)
        done: set[tuple[str, int]] = set()
        for seg in doc.segments:
            res = doc.results[seg.key]
            for pos, line_no in enumerate(seg.indices):
                if res.lines[pos].error and (seg.key, pos) not in done:
                    done.add((seg.key, pos))
                    self.retranslate(doc, line_no)
                    res = doc.results[seg.key]
                    yield doc

    def _neighbors(self, doc: Doc, seg: Segment) -> list[str]:
        """앞 구간 끝 2줄 + 뒤 구간 앞 2줄."""
        k = doc.segments.index(seg)
        before = doc.texts(doc.segments[k - 1])[-2:] if k > 0 else []
        after = doc.texts(doc.segments[k + 1])[:2] if k + 1 < len(doc.segments) else []
        return before + after

    def _save(self, key: str, res: SegResult) -> None:
        # 실패 줄이 있는 결과는 저장하지 않는다 → 다음에 다시 시도됨
        if self.cache is not None and res.ok:
            self.cache.put(key, res.to_dict())


# ================================================================ 결과 수정


def splice(res: SegResult, a: int, b: int, new: SegResult) -> SegResult:
    """res의 a~b줄(0-based, 포함)을 new로 교체한다. 문장 묶음도 함께 교체."""
    lines = res.lines[:a] + new.lines + res.lines[b + 1 :]
    keep = [s for s in res.sentences if s[1] < a or s[0] > b]
    moved = [(x + a, y + a, tr) for x, y, tr in new.sentences]
    return SegResult(lines, sorted(keep + moved))


def sentence_of(doc: Doc, line_no: int) -> Sentence:
    return next(s for s in doc.sentences() if s.start <= line_no <= s.end)


def chunks_to_text(chunks: list[Chunk]) -> str:
    """편집용 텍스트: 한 줄에 '원문 | 뜻'."""
    return "\n".join(f"{c.s} | {c.t}" for c in chunks)


def text_to_chunks(text: str) -> list[Chunk]:
    out = []
    for row in text.splitlines():
        if not row.strip():
            continue
        s, _, gloss = row.partition("|")
        if s.strip():
            out.append(Chunk(s.strip(), gloss.strip()))
    return out


def apply_edit(
    doc: Doc,
    line_no: int,
    chunks: list[Chunk],
    tr: str,
    sentence_tr: str | None = None,
    cache: Cache | None = None,
) -> None:
    """사용자가 직접 고친 내용을 반영한다. 구간이 모두 정상이면 캐시에도 저장."""
    seg, pos = doc.locate(line_no)
    res = doc.results.get(seg.key)
    if res is None:
        raise EditError("not_translated")
    if not chunks or not tr.strip():
        raise EditError("need_chunks")
    res.lines[pos] = SegLine(chunks, tr.strip())
    sents = []
    for a, b, s_tr in res.sentences:
        if a <= pos <= b:
            if a == b:
                s_tr = tr.strip()
            elif sentence_tr is not None and sentence_tr.strip():
                s_tr = sentence_tr.strip()
        sents.append((a, b, s_tr))
    res.sentences = sents
    if cache is not None and res.ok:
        cache.put(seg.key, res.to_dict())
