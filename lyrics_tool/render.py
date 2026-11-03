"""번역 결과 렌더링 (HTML 화면용 / Markdown 내보내기용).

보기 방식
  MODE_SOURCE : 원문 어순 — 의미 단위마다 원문 위, 한국어 아래로 나란히
  MODE_KOREAN : 한국어 어순 — 원문 아래 한국어 어순 직역
직역 단위 (한국어 어순에 적용)
  UNIT_LINE     : 줄마다 직역
  UNIT_SENTENCE : 여러 줄에 걸친 문장은 묶어서 한 번에 직역
"""

from __future__ import annotations

from html import escape

from .core import Doc, LineResult, Sentence

MODE_SOURCE = "원문 어순 (끊어읽기)"
MODE_KOREAN = "한국어 어순 (직역)"
MODES = [MODE_SOURCE, MODE_KOREAN]

UNIT_LINE = "줄 단위"
UNIT_SENTENCE = "문장 단위"
UNITS = [UNIT_LINE, UNIT_SENTENCE]

PENDING_TEXT = "번역 대기 중…"

CSS = """
.jk-wrap { font-size: 16px; line-height: 1.5; }
.jk-line { margin: 0 0 14px; }
.jk-sent { margin: 0 0 14px; padding-left: 8px; border-left: 3px solid rgba(127,127,127,.25); }
.jk-sent .jk-line { margin: 0; }
.jk-gap { height: 18px; }
.jk-no { display: inline-block; min-width: 2.2em; opacity: .45; font-size: 12px; vertical-align: top; padding-top: 4px; }
.jk-chunks { display: inline-flex; flex-wrap: wrap; gap: 4px 6px; vertical-align: top; max-width: calc(100% - 2.4em); }
.jk-chunk { display: inline-flex; flex-direction: column; padding: 3px 8px; border-radius: 6px;
            background: rgba(127,127,127,.10); border: 1px solid rgba(127,127,127,.18); }
.jk-s { font-weight: 600; }
.jk-k { font-size: 13px; opacity: .75; }
.jk-src { font-weight: 600; }
.jk-ko { margin-left: 2.4em; opacity: .85; }
.jk-err { margin-left: 2.4em; color: #d9534f; font-size: 13px; }
.jk-pending { opacity: .45; }
.jk-pending .jk-ko { font-style: italic; }
"""


def _no(i: int) -> str:
    return f'<span class="jk-no">{i}</span>'


def _src_line(r: LineResult) -> str:
    return f'<div class="jk-line">{_no(r.index)}<span class="jk-src">{escape(r.source)}</span></div>'


def _line_html(r: LineResult, mode: str) -> str:
    if r.pending:
        return (f'<div class="jk-line jk-pending">{_no(r.index)}<span class="jk-src">{escape(r.source)}</span>'
                f'<div class="jk-ko">{PENDING_TEXT}</div></div>')
    if r.error:
        return (f'<div class="jk-line">{_no(r.index)}<span class="jk-src">{escape(r.source)}</span>'
                f'<div class="jk-err">⚠ {escape(r.error)}</div></div>')
    if mode == MODE_SOURCE:
        cards = "".join(
            f'<span class="jk-chunk"><span class="jk-s">{escape(c.s)}</span>'
            f'<span class="jk-k">{escape(c.k)}</span></span>'
            for c in r.chunks
        )
        return f'<div class="jk-line">{_no(r.index)}<span class="jk-chunks">{cards}</span></div>'
    return (f'<div class="jk-line">{_no(r.index)}<span class="jk-src">{escape(r.source)}</span>'
            f'<div class="jk-ko">→ {escape(r.ko)}</div></div>')


def _sentence_html(s: Sentence, lines: list[LineResult]) -> str:
    group = lines[s.start - 1 : s.end]
    if s.start == s.end:
        return _line_html(group[0], MODE_KOREAN)
    srcs = "".join(_src_line(r) for r in group)
    if s.error:
        tail = f'<div class="jk-err">⚠ {escape(s.error)}</div>'
    else:
        tail = f'<div class="jk-ko">→ {escape(s.ko)}</div>'
    return f'<div class="jk-sent">{srcs}{tail}</div>'


def to_html(doc: Doc | None, mode: str, unit: str = UNIT_LINE) -> str:
    if doc is None:
        return '<div class="jk-wrap" style="opacity:.6">번역 결과가 여기에 표시됩니다.</div>'
    lines = doc.lines()
    rows: list[str] = []
    if mode == MODE_KOREAN and unit == UNIT_SENTENCE:
        starts = {s.start: s for s in doc.sentences()}
        covered: set[int] = set()
        for r in lines:
            if r.blank:
                rows.append('<div class="jk-gap"></div>')
            elif r.index in starts:
                s = starts[r.index]
                rows.append(_sentence_html(s, lines))
                covered.update(range(s.start, s.end + 1))
            elif r.index not in covered:
                rows.append(_line_html(r, mode))
    else:
        for r in lines:
            rows.append('<div class="jk-gap"></div>' if r.blank else _line_html(r, mode))
    return f'<style>{CSS}</style><div class="jk-wrap">{"".join(rows)}</div>'


def to_markdown(doc: Doc, mode: str, unit: str = UNIT_LINE) -> str:
    lines = doc.lines()
    out: list[str] = []

    def one(r: LineResult) -> str:
        if r.pending:
            return f"{r.source}  \n> {PENDING_TEXT}\n"
        if r.error:
            return f"{r.source}  \n> ⚠ {r.error}\n"
        if mode == MODE_SOURCE:
            return " / ".join(c.s for c in r.chunks) + "  \n" + " / ".join(c.k for c in r.chunks) + "\n"
        return f"{r.source}  \n→ {r.ko}\n"

    if mode == MODE_KOREAN and unit == UNIT_SENTENCE:
        starts = {s.start: s for s in doc.sentences()}
        covered: set[int] = set()
        for r in lines:
            if r.blank:
                out.append("")
            elif r.index in starts and starts[r.index].end > r.index:
                s = starts[r.index]
                srcs = "  \n".join(x.source for x in lines[s.start - 1 : s.end])
                tail = f"> ⚠ {s.error}" if s.error else f"→ {s.ko}"
                out.append(f"{srcs}  \n{tail}\n")
                covered.update(range(s.start, s.end + 1))
            elif r.index not in covered:
                out.append(one(r))
    else:
        out = ["" if r.blank else one(r) for r in lines]
    return "\n".join(out).strip() + "\n"
