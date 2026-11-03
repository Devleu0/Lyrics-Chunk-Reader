"""번역 결과 렌더링 (HTML 화면용 / Markdown 내보내기용).

MODE_SOURCE : 원문 어순 — 의미 단위마다 원문 위, 한국어 아래로 나란히
MODE_KOREAN : 한국어 어순 — 원문 한 줄 아래 한국어 어순 직역 한 줄
"""

from __future__ import annotations

from html import escape

from .core import LineResult

MODE_SOURCE = "원문 어순 (끊어읽기)"
MODE_KOREAN = "한국어 어순 (직역)"
MODES = [MODE_SOURCE, MODE_KOREAN]

CSS = """
.jk-wrap { font-size: 16px; line-height: 1.5; }
.jk-line { margin: 0 0 14px; }
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
"""


def _line_no(r: LineResult) -> str:
    return f'<span class="jk-no">{r.index}</span>'


def to_html(results: list[LineResult], mode: str) -> str:
    if not results:
        return '<div class="jk-wrap" style="opacity:.6">번역 결과가 여기에 표시됩니다.</div>'
    rows: list[str] = []
    for r in results:
        if r.blank:
            rows.append('<div class="jk-gap"></div>')
            continue
        if r.error:
            rows.append(
                f'<div class="jk-line">{_line_no(r)}<span class="jk-src">{escape(r.source)}</span>'
                f'<div class="jk-err">⚠ {escape(r.error)}</div></div>'
            )
            continue
        if mode == MODE_SOURCE:
            cards = "".join(
                f'<span class="jk-chunk"><span class="jk-s">{escape(c.s)}</span>'
                f'<span class="jk-k">{escape(c.k)}</span></span>'
                for c in r.chunks
            )
            rows.append(f'<div class="jk-line">{_line_no(r)}<span class="jk-chunks">{cards}</span></div>')
        else:
            rows.append(
                f'<div class="jk-line">{_line_no(r)}<span class="jk-src">{escape(r.source)}</span>'
                f'<div class="jk-ko">→ {escape(r.ko)}</div></div>'
            )
    return f'<style>{CSS}</style><div class="jk-wrap">{"".join(rows)}</div>'


def to_markdown(results: list[LineResult], mode: str) -> str:
    out: list[str] = []
    for r in results:
        if r.blank:
            out.append("")
            continue
        if r.error:
            out.append(f"{r.source}  \n> ⚠ {r.error}\n")
            continue
        if mode == MODE_SOURCE:
            src = " / ".join(c.s for c in r.chunks)
            ko = " / ".join(c.k for c in r.chunks)
            out.append(f"{src}  \n{ko}\n")
        else:
            out.append(f"{r.source}  \n→ {r.ko}\n")
    return "\n".join(out).strip() + "\n"
