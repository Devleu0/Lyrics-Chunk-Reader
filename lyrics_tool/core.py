"""직독직해 번역 코어.

흐름
  가사 → 줄 분리 → 연(빈 줄로 구분) 단위 구간(Segment)으로 나눔
       → 구간마다 LLM 1회 호출(JSON) → 검증 → 빠진 줄은 1줄씩(문맥 포함) 재시도
       → 구간 결과(SegResult)를 캐시에 저장

한 번의 호출로 세 가지를 함께 받는다. 그래서 보기 방식을 바꿔도 재호출하지 않는다.
  - 줄별 chunks : 원문 어순 의미 단위 + 한국어 대응
  - 줄별 ko     : 그 줄의 한국어 어순 직역
  - sentences   : 여러 줄에 걸친 문장을 묶은 범위 + 묶음 전체의 한국어 어순 직역

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

PROMPT_VERSION = 2
LANG_NAMES = {"ja": "일본어", "zh": "중국어", "en": "영어"}

_KANA = re.compile(r"[぀-ヿ]")
_HAN = re.compile(r"[一-鿿]")
_LATIN = re.compile(r"[A-Za-z]")


def detect_language(text: str) -> str:
    """가나가 있으면 일본어, 한자만 있으면 중국어, 그 외 라틴 문자면 영어."""
    if _KANA.search(text):
        return "ja"
    han = len(_HAN.findall(text))
    latin = len(_LATIN.findall(text))
    if han and han >= latin:
        return "zh"
    return "en"


# ================================================================ 데이터 모델


@dataclass
class Chunk:
    s: str  # 원문 조각
    k: str  # 한국어 대응


@dataclass
class SegLine:
    chunks: list[Chunk] = field(default_factory=list)
    ko: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.chunks) and bool(self.ko) and not self.error


@dataclass
class SegResult:
    """한 구간의 번역 결과. sentences는 구간 내 0-based 포함 범위 (start, end, ko)."""

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
            SegLine([Chunk(**c) for c in l["chunks"]], l["ko"], l.get("error", ""))
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
    ko: str = ""
    error: str = ""
    pending: bool = False

    @property
    def blank(self) -> bool:
        return not self.source.strip()

    @property
    def ok(self) -> bool:
        return self.blank or (bool(self.chunks) and bool(self.ko) and not self.error)


@dataclass
class Sentence:
    start: int  # 1-based, 포함
    end: int
    ko: str
    error: str = ""
    pending: bool = False


@dataclass
class Doc:
    lang: str
    sources: list[str]  # 0번 = 1번 줄
    segments: list[Segment]
    results: dict[str, SegResult] = field(default_factory=dict)

    # ---- 조회
    def locate(self, line_no: int) -> tuple[Segment, int]:
        for seg in self.segments:
            if line_no in seg.indices:
                return seg, seg.indices.index(line_no)
        raise KeyError(f"{line_no}번 줄은 번역 대상이 아닙니다(빈 줄이거나 범위 밖).")

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
                    r.chunks, r.ko, r.error = list(sl.chunks), sl.ko, sl.error
        return out

    def sentences(self) -> list[Sentence]:
        out: list[Sentence] = []
        for seg in self.segments:
            res = self.results.get(seg.key)
            if res is None:
                out += [Sentence(i, i, "", pending=True) for i in seg.indices]
                continue
            for a, b, ko in res.sentences:
                err = next((res.lines[p].error for p in range(a, b + 1) if res.lines[p].error), "")
                out.append(Sentence(seg.indices[a], seg.indices[b], ko, error=err))
        return sorted(out, key=lambda s: s.start)

    def progress(self) -> tuple[int, int]:
        keys = {s.key for s in self.segments}
        return len(keys & self.results.keys()), len(keys)

    def to_json(self) -> str:
        return json.dumps(
            {
                "lang": self.lang,
                "lines": [asdict(l) for l in self.lines()],
                "sentences": [asdict(s) for s in self.sentences()],
            },
            ensure_ascii=False,
            indent=2,
        )


# ================================================================ 프롬프트

_CHUNK_GUIDE = {
    "ja": (
        "일본어는 문절(文節) 단위로 끊는다: 내용어 + 뒤따르는 조사·조동사를 한 덩어리로. "
        "예) 君に / 会いたくて → 너를 / 만나고 싶어서. 조사의 뉘앙스(に·を·は·が·も)를 한국어 조사로 살린다."
    ),
    "zh": (
        "중국어는 의미 단위(주어구·동사구·목적어구·부사구·보어)로 끊는다. "
        "예) 我想 / 见到你 / 在这个夜晚 → 나는 ~하고 싶다 / 너를 만나다 / 이 밤에. "
        "了·过·着·得 같은 기능어는 앞 단어와 묶고 의미를 한국어로 반영한다."
    ),
    "en": (
        "영어는 끊어읽기(sense group) 단위로 끊는다: 주어 / 동사 / 목적어 / 전치사구 / 절. "
        "예) I've been waiting / for you / all night → 나는 기다려 왔어 / 너를 / 밤새."
    ),
}

SYSTEM_PROMPT = """너는 외국어 학습자를 돕는 문법 분석 도우미다.
사용자는 자신이 공부하려고 가져온 텍스트를 줄 단위로 준다. 너의 일은 학습용 직독직해 주석을 다는 것이다.
- 원문을 다시 써서 늘어놓거나 이어서 작성하지 않는다. 주어진 각 줄을 분석만 한다.
- 문학적 의역 금지. 학습자가 원문 구조를 따라갈 수 있도록 직역한다.
- 반드시 JSON 객체 하나만 출력한다. 설명·마크다운·사과문을 덧붙이지 않는다."""

_USER_TEMPLATE = """원문 언어: {lang_name}

[작업]
1. lines — 각 줄마다
   - "chunks": 원문을 어순 그대로 의미 단위로 끊고, 조각마다 한국어 대응어를 단다.
     "s"는 원문 조각 그대로이며, 모든 "s"를 이어 붙이면 원래 줄이 되어야 한다(공백 차이 허용).
     "k"는 그 조각만의 한국어 뜻. 원문 순서를 바꾸지 않는다.
   - "ko": 그 줄 하나를 자연스러운 한국어 어순으로 재배열한 직역. 단어 하나하나가 드러나야 하며 생략·창작 금지.
2. sentences — 문장 묶음
   - 연속된 줄이 한 문장(하나의 문법 단위)을 이루면 "from"~"to"로 묶고, 묶음 전체를 한국어 어순으로 직역한 "ko"를 단다.
   - 혼자 완결된 줄은 from과 to가 같은 묶음이 된다.
   - 모든 줄이 정확히 하나의 묶음에 속해야 하고, 묶음은 줄 순서대로 겹치지 않아야 한다.

[끊기 기준]
{chunk_guide}

[출력 형식]
{{"lines": [{{"i": 줄번호, "chunks": [{{"s": "원문조각", "k": "한국어"}}], "ko": "줄 직역"}}],
 "sentences": [{{"from": 시작줄, "to": 끝줄, "ko": "묶음 직역"}}]}}
입력의 모든 줄번호에 대해 lines 결과를 정확히 하나씩 낸다.
{context}
[입력]
{numbered}"""

_CONTEXT_TEMPLATE = """
[앞뒤 문맥 — 뜻 파악에만 참고하고 출력하지 말 것]
{context}
"""

_RETRY_NOTE = (
    "\n\n[참고] 이 요청은 학습자가 문장 구조를 이해하기 위한 문법 주석이며, "
    "원문 재현이 아니라 분석 결과만 필요하다. 형식을 지켜 JSON으로만 답하라."
)


def build_user_prompt(
    lines: list[tuple[int, str]], lang: str, retry: bool = False, context: list[str] | None = None
) -> str:
    numbered = "\n".join(f"{i}: {text}" for i, text in lines)
    ctx = _CONTEXT_TEMPLATE.format(context="\n".join(context)) if context else ""
    prompt = _USER_TEMPLATE.format(
        lang_name=LANG_NAMES.get(lang, lang),
        chunk_guide=_CHUNK_GUIDE.get(lang, _CHUNK_GUIDE["en"]),
        context=ctx,
        numbered=numbered,
    )
    return prompt + (_RETRY_NOTE if retry else "")


# ================================================================ 응답 파싱

_REFUSAL_HINTS = (
    "죄송", "도와드릴 수 없", "제공할 수 없", "저작권",
    "i'm sorry", "i am sorry", "i can't", "i cannot", "copyright", "unable to",
)


def _extract_json(text: str) -> dict:
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
        raise RefusalError(f"모델이 거부했습니다: {text[:120]}")
    raise ValueError(f"JSON 파싱 실패: {text[:120]}")


def _norm(s: str) -> str:
    return re.sub(r"[\s　]+", "", s)


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def parse_response(
    text: str, expected: dict[int, str]
) -> tuple[dict[int, SegLine], list[tuple[int, int, str]]]:
    """유효한 줄과 (검증 전) 문장 묶음 목록을 반환한다. 빠진 줄은 호출자가 재시도한다."""
    data = _extract_json(text)
    items = data.get("lines") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("응답에 'lines' 배열이 없습니다.")

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
            Chunk(s=str(c.get("s", "")).strip(), k=str(c.get("k", "")).strip())
            for c in item.get("chunks") or []
            if isinstance(c, dict) and str(c.get("s", "")).strip()
        ]
        ko = str(item.get("ko", "")).strip()
        if not chunks or not ko:
            continue
        # 조각을 이으면 원문이 되는지 확인 — 다른 줄을 끌어오거나 창작한 응답을 걸러낸다.
        if _similarity(_norm("".join(c.s for c in chunks)), _norm(expected[i])) < 0.8:
            continue
        lines[i] = SegLine(chunks, ko)

    sentences: list[tuple[int, int, str]] = []
    raw_sents = data.get("sentences") if isinstance(data, dict) else None
    for s in raw_sents or []:
        if not isinstance(s, dict):
            continue
        try:
            a, b = int(s.get("from")), int(s.get("to"))
        except (TypeError, ValueError):
            continue
        ko = str(s.get("ko", "")).strip()
        if ko:
            sentences.append((a, b, ko))
    return lines, sentences


def normalize_sentences(
    n: int, lines: list[SegLine], raw: list[tuple[int, int, str]], base: int = 1
) -> list[tuple[int, int, str]]:
    """모델이 준 묶음(base 기준 번호)을 검증해 0-based 범위로 바꾸고, 빈 곳은 한 줄짜리 묶음으로 채운다.

    범위를 벗어나거나 겹치거나, 실패한 줄을 포함한 묶음은 버린다.
    """
    taken = [False] * n
    out: list[tuple[int, int, str]] = []
    for a, b, ko in sorted(raw):
        a, b = a - base, b - base
        if not (0 <= a <= b < n) or any(taken[a : b + 1]):
            continue
        if not all(lines[p].ok for p in range(a, b + 1)):
            continue
        if a == b:
            ko = lines[a].ko  # 한 줄 묶음은 줄 직역과 같게 맞춘다
        out.append((a, b, ko))
        for p in range(a, b + 1):
            taken[p] = True
    for p in range(n):
        if not taken[p]:
            out.append((p, p, lines[p].ko))
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
    ):
        self.backend = backend
        self.batch_size = max(1, batch_size)
        self.max_attempts = max(1, max_attempts)
        self.cache = cache

    # ---- 키
    def segment_key(self, lang: str, texts: list[str]) -> str:
        return make_key(PROMPT_VERSION, self.backend.name, self.backend.model, lang, texts)

    # ---- 준비 / 실행
    def prepare(self, lyrics: str, lang: str = "auto", use_cache: bool = True) -> Doc:
        sources = [l.strip() for l in lyrics.replace("\r\n", "\n").split("\n")]
        if lang == "auto":
            lang = detect_language(lyrics)
        segments = []
        for idx in split_segments(sources, self.batch_size):
            texts = [sources[i - 1] for i in idx]
            segments.append(Segment(self.segment_key(lang, texts), idx))
        doc = Doc(lang, sources, segments)
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
        raw = self.backend.chat(SYSTEM_PROMPT, build_user_prompt(lines, lang, retry, context))
        return parse_response(raw, dict(lines))

    def translate_lines(
        self, texts: list[str], lang: str, context: list[str] | None = None
    ) -> SegResult:
        numbered = list(enumerate(texts, start=1))
        got: dict[int, SegLine] = {}
        raw_sents: list[tuple[int, int, str]] = []

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
            got.update(lines)
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
                    got[i] = one[1]
                    break
                last = "응답 형식이 맞지 않음"
            else:
                got[i] = SegLine(error=last or "번역 실패")

        lines = [got[i] for i, _ in numbered]
        return SegResult(lines, normalize_sentences(len(lines), lines, raw_sents))

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
    moved = [(x + a, y + a, ko) for x, y, ko in new.sentences]
    return SegResult(lines, sorted(keep + moved))


def sentence_of(doc: Doc, line_no: int) -> Sentence:
    return next(s for s in doc.sentences() if s.start <= line_no <= s.end)


def chunks_to_text(chunks: list[Chunk]) -> str:
    """편집용 텍스트: 한 줄에 '원문 | 한국어'."""
    return "\n".join(f"{c.s} | {c.k}" for c in chunks)


def text_to_chunks(text: str) -> list[Chunk]:
    out = []
    for row in text.splitlines():
        if not row.strip():
            continue
        s, _, k = row.partition("|")
        if s.strip():
            out.append(Chunk(s.strip(), k.strip()))
    return out


def apply_edit(
    doc: Doc,
    line_no: int,
    chunks: list[Chunk],
    ko: str,
    sentence_ko: str | None = None,
    cache: Cache | None = None,
) -> None:
    """사용자가 직접 고친 내용을 반영한다. 구간이 모두 정상이면 캐시에도 저장."""
    seg, pos = doc.locate(line_no)
    res = doc.results.get(seg.key)
    if res is None:
        raise ValueError("아직 번역되지 않은 줄입니다.")
    if not chunks or not ko.strip():
        raise ValueError("청크와 줄 직역을 모두 입력해 주세요.")
    res.lines[pos] = SegLine(chunks, ko.strip())
    sents = []
    for a, b, s_ko in res.sentences:
        if a <= pos <= b:
            if a == b:
                s_ko = ko.strip()
            elif sentence_ko is not None and sentence_ko.strip():
                s_ko = sentence_ko.strip()
        sents.append((a, b, s_ko))
    res.sentences = sents
    if cache is not None and res.ok:
        cache.put(seg.key, res.to_dict())
