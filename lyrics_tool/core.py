"""직독직해 번역 코어.

흐름: 가사 → 줄 분리 → N줄 배치로 LLM 호출(JSON) → 검증
      → 실패/거부된 줄은 1줄씩 재시도 → LineResult 목록.

한 번의 호출로 두 가지 결과를 함께 받는다.
- chunks : 원문 어순 그대로 끊은 의미 단위 + 각 단위의 한국어 대응어
- ko     : 한국어 어순으로 재배열한 직역(의역 아님)
그래서 UI에서 모드를 바꿔도 LLM을 다시 부르지 않는다.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Callable

from .backends import Backend, BackendError, RefusalError

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


# ---------------------------------------------------------------- 데이터 모델


@dataclass
class Chunk:
    s: str  # 원문 조각
    k: str  # 한국어 대응


@dataclass
class LineResult:
    index: int
    source: str
    chunks: list[Chunk] = field(default_factory=list)
    ko: str = ""
    error: str = ""

    @property
    def blank(self) -> bool:
        return not self.source.strip()

    @property
    def ok(self) -> bool:
        return self.blank or (bool(self.chunks) and bool(self.ko) and not self.error)


def results_to_json(results: list[LineResult], lang: str) -> str:
    return json.dumps(
        {"lang": lang, "lines": [asdict(r) for r in results]}, ensure_ascii=False, indent=2
    )


# ---------------------------------------------------------------- 프롬프트

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
각 줄마다
1. "chunks": 원문을 어순 그대로 의미 단위로 끊고, 조각마다 한국어 대응어를 단다.
   - "s"는 원문 조각을 그대로 옮긴 것이며, 모든 "s"를 이어 붙이면 원래 줄이 되어야 한다(공백 차이는 허용).
   - "k"는 그 조각만의 한국어 뜻. 원문 순서를 바꾸지 않는다.
2. "ko": 한 줄 전체를 자연스러운 한국어 어순으로 재배열한 직역.
   - 원문의 단어 하나하나가 드러나야 한다. 생략·과장·창작 금지.

[끊기 기준]
{chunk_guide}

[출력 형식]
{{"lines": [{{"i": 줄번호, "chunks": [{{"s": "원문조각", "k": "한국어"}}], "ko": "한국어 어순 직역"}}]}}
입력의 모든 줄번호에 대해 정확히 하나씩 결과를 낸다.

[입력]
{numbered}"""

_RETRY_NOTE = (
    "\n\n[참고] 이 요청은 학습자가 문장 구조를 이해하기 위한 문법 주석이며, "
    "원문 재현이 아니라 분석 결과만 필요하다. 형식을 지켜 JSON으로만 답하라."
)


def build_user_prompt(lines: list[tuple[int, str]], lang: str, retry: bool = False) -> str:
    numbered = "\n".join(f"{i}: {text}" for i, text in lines)
    prompt = _USER_TEMPLATE.format(
        lang_name=LANG_NAMES.get(lang, lang),
        chunk_guide=_CHUNK_GUIDE.get(lang, _CHUNK_GUIDE["en"]),
        numbered=numbered,
    )
    return prompt + (_RETRY_NOTE if retry else "")


# ---------------------------------------------------------------- 응답 파싱

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


def parse_response(text: str, expected: dict[int, str]) -> dict[int, LineResult]:
    """모델 응답에서 유효한 줄만 골라 반환한다. 빠진 줄은 호출자가 재시도한다."""
    data = _extract_json(text)
    items = data.get("lines") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("응답에 'lines' 배열이 없습니다.")

    out: dict[int, LineResult] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            i = int(item.get("i"))
        except (TypeError, ValueError):
            continue
        if i not in expected or i in out:
            continue
        chunks = [
            Chunk(s=str(c.get("s", "")).strip(), k=str(c.get("k", "")).strip())
            for c in item.get("chunks") or []
            if isinstance(c, dict) and str(c.get("s", "")).strip()
        ]
        ko = str(item.get("ko", "")).strip()
        if not chunks or not ko:
            continue
        # 조각을 이으면 원문이 되는지 확인 — 모델이 다른 줄을 끌어오거나 창작했는지 걸러낸다.
        joined, src = _norm("".join(c.s for c in chunks)), _norm(expected[i])
        if _similarity(joined, src) < 0.8:
            continue
        out[i] = LineResult(index=i, source=expected[i], chunks=chunks, ko=ko)
    return out


def _similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------- 번역기


ProgressFn = Callable[[int, int, str], None]


class Translator:
    def __init__(self, backend: Backend, batch_size: int = 8, max_attempts: int = 2):
        self.backend = backend
        self.batch_size = max(1, batch_size)
        self.max_attempts = max(1, max_attempts)

    def _call(self, lines: list[tuple[int, str]], lang: str, retry: bool) -> dict[int, LineResult]:
        raw = self.backend.chat(SYSTEM_PROMPT, build_user_prompt(lines, lang, retry))
        return parse_response(raw, dict(lines))

    def translate(
        self, lyrics: str, lang: str = "auto", progress: ProgressFn | None = None
    ) -> tuple[list[LineResult], str]:
        """가사 전체를 번역한다. (결과 목록, 확정 언어 코드)를 반환."""
        raw_lines = lyrics.replace("\r\n", "\n").split("\n")
        if lang == "auto":
            lang = detect_language(lyrics)

        results = [LineResult(index=n + 1, source=t.strip()) for n, t in enumerate(raw_lines)]
        # 빈 줄(연 구분)은 보내지 않는다. 같은 줄이 반복되는 후렴은 한 번만 번역해 재사용.
        unique: dict[str, int] = {}
        todo: list[tuple[int, str]] = []
        for r in results:
            if r.blank or r.source in unique:
                continue
            unique[r.source] = r.index
            todo.append((r.index, r.source))

        done: dict[int, LineResult] = {}
        total = len(todo)

        def report(msg: str) -> None:
            if progress:
                progress(len(done), total, msg)

        # 1단계: 배치 번역
        for b in range(0, total, self.batch_size):
            batch = todo[b : b + self.batch_size]
            report(f"{b + 1}–{b + len(batch)}줄 번역 중")
            try:
                done.update(self._call(batch, lang, retry=False))
            except (RefusalError, ValueError):
                pass  # 2단계에서 줄 단위로 다시 시도
            except BackendError:
                raise

        # 2단계: 빠진 줄을 1줄씩 재시도 (작은 단위가 저작물 필터·거부를 덜 탄다)
        errors: dict[int, str] = {}
        for i, text in todo:
            if i in done:
                continue
            report(f"{i}번 줄 재시도 중")
            last = ""
            for _ in range(self.max_attempts):
                try:
                    got = self._call([(i, text)], lang, retry=True)
                except RefusalError as e:
                    last = str(e)
                    continue
                except ValueError as e:
                    last = str(e)
                    continue
                if i in got:
                    done[i] = got[i]
                    break
                last = "응답 형식이 맞지 않음"
            else:
                errors[i] = last or "번역 실패"

        # 결과 조립 (반복 줄은 첫 번역을 복사)
        for r in results:
            if r.blank:
                continue
            first = unique[r.source]
            if first in done:
                src = done[first]
                r.chunks, r.ko = list(src.chunks), src.ko
            else:
                r.error = errors.get(first, "번역 실패")
        report("완료")
        return results, lang
