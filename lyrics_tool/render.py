"""번역 결과 렌더링 (화면 HTML / 인쇄용 HTML / Markdown).

보기 방식 (값은 코드, 화면 이름은 i18n)
  MODE_SOURCE : 원문 어순 — 의미 단위마다 원문 위, 뜻 아래로 나란히
  MODE_TARGET : 번역 어순 — 원문 아래 번역 언어 어순 직역
  MODE_BOTH   : 둘 다 — 끊어읽기 카드 아래 직역
직역 단위 (직역이 보이는 방식에 적용)
  UNIT_LINE     : 줄마다 직역
  UNIT_SENTENCE : 여러 줄에 걸친 문장은 묶어서 한 번에 직역
읽기 보조 (ViewOptions)
  reading    : 일본어 후리가나·중국어 병음을 원문 위에 표시
  dictionary : 청크 원문을 휠 클릭(또는 Ctrl+클릭)하면 외부 사전 검색
청크 원문을 좌클릭하면 브라우저 TTS로 읽는다 (화면 HTML만. 인쇄용은 링크만 둔다)
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from .core import Doc, LineResult, Sentence
from .i18n import t as _t
from .reading import DICT_NAVER, available, dict_url, ruby_html, ruby_text

MODE_SOURCE = "source"
MODE_TARGET = "target"
MODE_BOTH = "both"
MODES = [MODE_SOURCE, MODE_TARGET, MODE_BOTH]

UNIT_LINE = "line"
UNIT_SENTENCE = "sentence"
UNITS = [UNIT_LINE, UNIT_SENTENCE]


def mode_label(mode: str, ui: str) -> str:
    return _t(ui, f"mode_{mode}")


def unit_label(unit: str, ui: str) -> str:
    return _t(ui, f"unit_{unit}")


@dataclass
class ViewOptions:
    font_size: int = 16
    show_numbers: bool = True
    hide_translation: bool = False  # 셀프 테스트: 뜻·직역을 흐리게, 누르거나 올리면 보임
    reading: bool = True  # 후리가나·병음
    dictionary: str = DICT_NAVER
    ui: str = "en"  # 안내 문구 언어


@dataclass
class _Ctx:
    mode: str
    hide: bool
    lang: str
    ruby: bool
    dictionary: str
    ui: str
    tts: bool

    @classmethod
    def make(cls, doc: Doc, mode: str, opts: ViewOptions, tts: bool) -> "_Ctx":
        return cls(mode, opts.hide_translation, doc.lang, opts.reading and available(doc.lang), opts.dictionary,
                   opts.ui, tts)

    def src(self, text: str) -> str:
        return ruby_html(text, self.lang) if self.ruby else escape(text)


CSS = """
.jk-wrap { font-size: var(--jk-fs, 16px); line-height: 1.5; }
.jk-line { margin: 0 0 .9em; }
.jk-sent { margin: 0 0 .9em; padding-left: 8px; border-left: 3px solid rgba(127,127,127,.25); }
.jk-sent .jk-line { margin: 0 0 .25em; }
.jk-gap { height: 1.1em; }
.jk-no { display: inline-block; min-width: 2.2em; opacity: .45; font-size: .75em; vertical-align: top; padding-top: .3em;
         cursor: pointer; user-select: none; }
.jk-no:hover { opacity: 1; text-decoration: underline; }
.jk-empty { opacity: .6; padding: 48px 8px; text-align: center; line-height: 1.8; }
.jk-nonum .jk-no { display: none; }
.jk-nonum .jk-tr, .jk-nonum .jk-err { margin-left: 0; }
.jk-nonum .jk-chunks { max-width: 100%; }
.jk-chunks { display: inline-flex; flex-wrap: wrap; gap: 4px 6px; vertical-align: top; max-width: calc(100% - 2.4em); }
.jk-chunk { display: inline-flex; flex-direction: column; padding: 3px 8px; border-radius: 6px;
            background: rgba(127,127,127,.10); border: 1px solid rgba(127,127,127,.18); }
.jk-s { font-weight: 600; }
.jk-t { font-size: .82em; opacity: .75; }
.jk-src { font-weight: 600; }
.jk-tr { margin-left: 2.4em; opacity: .85; }
.jk-err { margin-left: 2.4em; color: #d9534f; font-size: .82em; }
.jk-pending { opacity: .45; }
.jk-pending .jk-tr { font-style: italic; }
.jk-hide .jk-t, .jk-hide .jk-tr:not(.jk-wait) { filter: blur(5px); cursor: pointer; transition: filter .15s; outline: none; }
.jk-wrap a.jk-s, .jk-wrap a.jk-s:visited { color: inherit !important; text-decoration: none !important; }
.jk-wrap a.jk-s:hover, .jk-wrap a.jk-s:focus { text-decoration: underline dotted !important; }
.jk-s[data-tts] { cursor: pointer; border-radius: 3px; }
.jk-s.jk-speaking { background: rgba(255,170,0,.28); }
.jk-wrap rt { font-size: .55em; font-weight: 400; opacity: .7; }
.jk-hide .jk-t:hover, .jk-hide .jk-t:focus, .jk-hide .jk-tr:hover, .jk-hide .jk-tr:focus { filter: none; }
"""

PRINT_CSS = """
body { font-family: -apple-system, "Apple SD Gothic Neo", "Noto Sans KR", "Noto Sans JP", "Noto Sans SC", sans-serif;
       color: #111; background: #fff; max-width: 820px; margin: 32px auto; padding: 0 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
.meta { color: #666; font-size: 12px; margin-bottom: 24px; }
.jk-chunk { background: #f4f4f4; border-color: #ddd; }
.jk-line, .jk-sent { break-inside: avoid; }
@media print { body { margin: 0 auto; } .jk-hide .jk-t, .jk-hide .jk-tr { filter: none !important; } }
"""


def _no(i: int) -> str:
    return f'<span class="jk-no">{i}</span>'


def _tr(text: str, hide: bool) -> str:
    tab = ' tabindex="0"' if hide else ""
    return f'<div class="jk-tr"{tab}>→ {escape(text)}</div>'


def _chunk_src(text: str, c: _Ctx) -> str:
    """좌클릭은 TTS(APP_JS가 처리), 휠 클릭은 href의 사전이 새 탭으로 열린다."""
    url = dict_url(text, c.lang, c.dictionary)
    tts = f' data-tts="{escape(text)}"' if c.tts else ""
    if not url:
        title = f' title="{_t(c.ui, "tts_title")}"' if c.tts else ""
        return f'<span class="jk-s"{tts}{title}>{c.src(text)}</span>'
    title = _t(c.ui, "tts_dict_title" if c.tts else "dict_title")
    return (f'<a class="jk-s" href="{escape(url)}" target="_blank" rel="noopener noreferrer"{tts} '
            f'title="{title}">{c.src(text)}</a>')


def _head(r: LineResult, c: _Ctx) -> str:
    """줄의 원문 부분 — 끊어읽기 카드 또는 원문 한 줄."""
    if c.mode != MODE_TARGET and r.chunks and not r.error and not r.pending:
        tab = ' tabindex="0"' if c.hide else ""
        cards = "".join(
            f'<span class="jk-chunk">{_chunk_src(ch.s, c)}'
            f'<span class="jk-t"{tab}>{escape(ch.t)}</span></span>'
            for ch in r.chunks
        )
        return f'{_no(r.index)}<span class="jk-chunks">{cards}</span>'
    return f'{_no(r.index)}<span class="jk-src">{c.src(r.source)}</span>'


def _line_html(r: LineResult, c: _Ctx) -> str:
    if r.pending:
        return (f'<div class="jk-line jk-pending">{_head(r, c)}'
                f'<div class="jk-tr jk-wait">{_t(c.ui, "pending")}</div></div>')
    if r.error:
        return f'<div class="jk-line">{_head(r, c)}<div class="jk-err">⚠ {escape(r.error)}</div></div>'
    tail = "" if c.mode == MODE_SOURCE else _tr(r.tr, c.hide)
    return f'<div class="jk-line">{_head(r, c)}{tail}</div>'


def _sentence_html(s: Sentence, lines: list[LineResult], c: _Ctx) -> str:
    group = lines[s.start - 1 : s.end]
    if s.start == s.end:
        return _line_html(group[0], c)
    heads = "".join(f'<div class="jk-line">{_head(r, c)}</div>' for r in group)
    tail = f'<div class="jk-err">⚠ {escape(s.error)}</div>' if s.error else _tr(s.tr, c.hide)
    return f'<div class="jk-sent">{heads}{tail}</div>'


def _body(doc: Doc, mode: str, unit: str, opts: ViewOptions, tts: bool = True) -> str:
    lines = doc.lines()
    c = _Ctx.make(doc, mode, opts, tts)
    rows: list[str] = []
    if mode != MODE_SOURCE and unit == UNIT_SENTENCE:
        starts = {s.start: s for s in doc.sentences()}
        covered: set[int] = set()
        for r in lines:
            if r.blank:
                rows.append('<div class="jk-gap"></div>')
            elif r.index in starts:
                s = starts[r.index]
                rows.append(_sentence_html(s, lines, c))
                covered.update(range(s.start, s.end + 1))
            elif r.index not in covered:
                rows.append(_line_html(r, c))
    else:
        for r in lines:
            rows.append('<div class="jk-gap"></div>' if r.blank else _line_html(r, c))
    classes = ["jk-wrap"]
    if not opts.show_numbers:
        classes.append("jk-nonum")
    if c.hide:
        classes.append("jk-hide")
    lang = f' data-lang="{escape(doc.lang)}" data-no-voice="{_t(opts.ui, "tts_no_voice")}"' if tts else ""
    return (f'<div class="{" ".join(classes)}"{lang} style="--jk-fs:{int(opts.font_size)}px">'
            f'{"".join(rows)}</div>')


def to_html(doc: Doc | None, mode: str, unit: str = UNIT_LINE, opts: ViewOptions | None = None) -> str:
    opts = opts or ViewOptions()
    if doc is None:
        return f'<style>{CSS}</style><div class="jk-wrap jk-empty">{_t(opts.ui, "empty")}</div>'
    return f"<style>{CSS}</style>{_body(doc, mode, unit, opts)}"


def to_print_html(doc: Doc, mode: str, unit: str, opts: ViewOptions | None, title: str, meta: str = "") -> str:
    """브라우저에서 열어 인쇄하거나 PDF로 저장할 수 있는 단독 HTML."""
    opts = opts or ViewOptions()
    return (
        f"<!doctype html><html lang=\"{opts.ui}\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{escape(title)}</title><style>{CSS}{PRINT_CSS}</style></head><body>"
        f"<h1>{escape(title)}</h1><div class=\"meta\">{escape(meta)}</div>"
        f"{_body(doc, mode, unit, opts, tts=False)}</body></html>"
    )


def to_markdown(doc: Doc, mode: str, unit: str = UNIT_LINE, opts: ViewOptions | None = None) -> str:
    lines = doc.lines()
    out: list[str] = []
    opts = opts or ViewOptions()
    ruby = opts.reading and available(doc.lang)

    def src(text: str) -> str:
        return ruby_text(text, doc.lang) if ruby else text

    def head(r: LineResult) -> str:
        if mode != MODE_TARGET and r.chunks:
            return " / ".join(src(c.s) for c in r.chunks) + "  \n" + " / ".join(c.t for c in r.chunks)
        return src(r.source)

    def one(r: LineResult) -> str:
        if r.pending:
            return f"{r.source}  \n> {_t(opts.ui, 'pending')}\n"
        if r.error:
            return f"{r.source}  \n> ⚠ {r.error}\n"
        if mode == MODE_SOURCE:
            return head(r) + "\n"
        return f"{head(r)}  \n→ {r.tr}\n"

    if mode != MODE_SOURCE and unit == UNIT_SENTENCE:
        starts = {s.start: s for s in doc.sentences()}
        covered: set[int] = set()
        for r in lines:
            if r.blank:
                out.append("")
            elif r.index in starts and starts[r.index].end > r.index:
                s = starts[r.index]
                heads = "  \n".join(head(x) for x in lines[s.start - 1 : s.end])
                tail = f"> ⚠ {s.error}" if s.error else f"→ {s.tr}"
                out.append(f"{heads}  \n{tail}\n")
                covered.update(range(s.start, s.end + 1))
            elif r.index not in covered:
                out.append(one(r))
    else:
        out = ["" if r.blank else one(r) for r in lines]
    return "\n".join(out).strip() + "\n"
