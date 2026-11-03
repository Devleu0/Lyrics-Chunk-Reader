"""발음 표기(후리가나·병음)와 사전 링크.

LLM을 쓰지 않고 로컬 라이브러리로 처리한다. 라이브러리가 없으면 표기 없이 원문만 돌려준다.
  일본어 : fugashi + unidic-lite(형태소 분석) — 한자 위에 히라가나. 오쿠리가나는 빼고 한자 부분에만 단다
           (待って → 待(ま)って)
  중국어 : pypinyin — 한자마다 성조 기호 병음. 단어 사전으로 다음자(多音字)를 고르므로 조각째 넘긴다
사전 링크는 청크 원문을 외부 사전 검색 주소로 바꿀 뿐이며, 누를 때만 그 사이트로 전송된다.
"""

from __future__ import annotations

import re
from functools import lru_cache
from html import escape
from urllib.parse import quote

Piece = tuple[str, str]  # (원문 조각, 읽기 — 없으면 "")

_KANJI = r"[㐀-䶿一-鿿豈-﫿々〆]+"
_KANJI_RUN = re.compile(_KANJI)
_HAN_RUN = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")
_KATA = re.compile(r"[ァ-ヶ]")

DICT_NAVER = "naver"  # 한국어 뜻 (일·중·영·한)
DICT_INTL = "intl"  # 일본어 Jisho, 중국어 MDBG, 그 밖은 Wiktionary
DICT_OFF = "off"
DICTS = [DICT_NAVER, DICT_INTL, DICT_OFF]
_WIKTIONARY = "https://en.wiktionary.org/wiki/Special:Search?search={}"

_URLS = {
    DICT_NAVER: {
        "ja": "https://ja.dict.naver.com/#/search?query={}",
        "zh": "https://zh.dict.naver.com/#/search?query={}",
        "en": "https://en.dict.naver.com/#/search?query={}",
        "ko": "https://ko.dict.naver.com/#/search?query={}",
    },
    DICT_INTL: {
        "ja": "https://jisho.org/search/{}",
        "zh": "https://www.mdbg.net/chinese/dictionary?page=worddict&wdqb={}",
    },
}
_EDGE_PUNCT = re.compile(r"^[\W_]+|[\W_]+$")


@lru_cache(maxsize=1)
def _tagger():
    try:
        import fugashi

        return fugashi.Tagger()
    except Exception:  # 미설치 또는 사전 없음
        return None


@lru_cache(maxsize=1)
def _pinyin():
    try:
        from pypinyin import Style, lazy_pinyin, load_phrases_dict
    except ImportError:
        return None
    load_phrases_dict({"重来": [["chóng"], ["lái"]]})  # pypinyin 사전에 빠진 가사 빈출 단어
    return lambda s: lazy_pinyin(s, style=Style.TONE)


def available(lang: str) -> bool:
    return (lang == "ja" and _tagger() is not None) or (lang == "zh" and _pinyin() is not None)


def _to_hira(s: str) -> str:
    return _KATA.sub(lambda m: chr(ord(m.group()) - 0x60), s)


def _align(orig: str, kana: str) -> list[Piece]:
    """한자 덩어리에만 읽기를 나눠 단다. '引き出し'·'ひきだし' → 引(ひ) き 出(だ) し"""
    parts = [p for p in re.split(f"({_KANJI})", orig) if p]
    pattern = "".join("(.+?)" if _KANJI_RUN.fullmatch(p) else re.escape(_to_hira(p)) for p in parts)
    m = re.fullmatch(pattern, kana)
    if not m:
        return [(orig, kana)]
    groups = iter(m.groups())
    return [(p, next(groups)) if _KANJI_RUN.fullmatch(p) else (p, "") for p in parts]


def _ja(text: str) -> list[Piece]:
    out: list[Piece] = []
    pos = 0
    for w in _tagger()(text):
        start = text.find(w.surface, pos)  # 형태소 사이의 공백을 살린다
        if start > pos:
            out.append((text[pos:start], ""))
        pos = start + len(w.surface)
        kana = getattr(w.feature, "kana", None)
        if _KANJI_RUN.search(w.surface) and kana and kana != "*":
            out.extend(_align(w.surface, _to_hira(kana)))
        else:
            out.append((w.surface, ""))
    out.append((text[pos:], ""))
    return out


def _zh(text: str) -> list[Piece]:
    py = _pinyin()
    out: list[Piece] = []
    pos = 0
    for m in _HAN_RUN.finditer(text):
        out.append((text[pos : m.start()], ""))
        run = m.group()
        readings = py(run)
        if len(readings) != len(run):  # 사전에 없는 글자가 섞이면 한 글자씩
            readings = [py(ch)[0] for ch in run]
        out.extend((ch, r if r != ch else "") for ch, r in zip(run, readings))
        pos = m.end()
    out.append((text[pos:], ""))
    return out


@lru_cache(maxsize=4096)
def pieces(text: str, lang: str) -> tuple[Piece, ...]:
    """원문을 (조각, 읽기)로 나눈다. 읽기가 없는 이웃 조각은 합친다."""
    if not text or not available(lang):
        return ((text, ""),) if text else ()
    raw = _ja(text) if lang == "ja" else _zh(text)
    out: list[Piece] = []
    for s, r in raw:
        if not s:
            continue
        if not r and out and not out[-1][1]:
            out[-1] = (out[-1][0] + s, "")
        else:
            out.append((s, r))
    return tuple(out)


def ruby_html(text: str, lang: str) -> str:
    return "".join(
        f"<ruby>{escape(s)}<rt>{escape(r)}</rt></ruby>" if r else escape(s) for s, r in pieces(text, lang)
    )


def ruby_text(text: str, lang: str) -> str:
    """Markdown용. 일본어는 待(ま)って, 중국어는 원문 뒤에 병음을 모아 我爱你 (wǒ ài nǐ)."""
    ps = pieces(text, lang)
    if lang == "zh":
        readings = [r for _, r in ps if r]
        return f"{text} ({' '.join(readings)})" if readings else text
    return "".join(f"{s}({r})" if r else s for s, r in ps)


def dict_url(text: str, lang: str, dictionary: str) -> str:
    """네이버가 없는 언어는 Wiktionary로 연결한다."""
    tmpl = _URLS[dictionary].get(lang, _WIKTIONARY) if dictionary in _URLS else None
    query = _EDGE_PUNCT.sub("", text.strip())
    if not tmpl or not query:
        return ""
    return tmpl.format(quote(query, safe=""))
