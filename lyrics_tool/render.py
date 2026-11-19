"""번역 결과 렌더링 (화면 HTML / 인쇄용 HTML / 모바일 HTML / 이미지용 HTML / Markdown).

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

from .assets import read as _asset
from .core import Doc, LineResult, Sentence
from .i18n import t as _t
from .reading import DICT_NAVER, DICT_OFF, available, dict_url, ruby_html, ruby_text

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
    target: str = ""

    @classmethod
    def make(cls, doc: Doc, mode: str, opts: ViewOptions, tts: bool) -> _Ctx:
        return cls(mode, opts.hide_translation, doc.lang, opts.reading and available(doc.lang), opts.dictionary,
                   opts.ui, tts, doc.target)

    @property
    def tl(self) -> str:
        """뜻·직역에 다는 lang 속성 (언어별 글꼴을 고르게)."""
        return f' lang="{escape(self.target)}"' if self.target else ""

    @property
    def ul(self) -> str:
        """안내·오류 문구(화면 언어)에 다는 lang 속성."""
        return f' lang="{escape(self.ui)}"'

    def src(self, text: str) -> str:
        return ruby_html(text, self.lang) if self.ruby else escape(text)


CSS = _asset("view.css")

PRINT_CSS = _asset("print.css")


def _no(i: int) -> str:
    return f'<span class="jk-no">{i}</span>'


def _tr(text: str, c: _Ctx) -> str:
    tab = ' tabindex="0"' if c.hide else ""
    return f'<div class="jk-tr"{tab}{c.tl}><span class="jk-arrow" aria-hidden="true">→</span> {escape(text)}</div>'


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


def _play(r: LineResult, c: _Ctx) -> str:
    """줄 원문 듣기 버튼 (TTS를 쓰는 화면만). 앱은 서버 음성, 모바일 HTML은 브라우저 음성으로 읽는다."""
    if not c.tts:
        return ""
    return (f'<span class="jk-play" role="button" tabindex="0" data-line="{r.index}" data-tts="{escape(r.source)}" '
            f'title="{_t(c.ui, "play_line")}">▶</span>')


def _head(r: LineResult, c: _Ctx) -> str:
    """줄의 원문 부분 — 끊어읽기 카드 또는 원문 한 줄."""
    if c.mode != MODE_TARGET and r.chunks and not r.error and not r.pending:
        tab = ' tabindex="0"' if c.hide else ""
        cards = "".join(
            f'<span class="jk-chunk">{_chunk_src(ch.s, c)}'
            f'<span class="jk-t"{tab}{c.tl}>{escape(ch.t)}</span></span>'
            for ch in r.chunks
        )
        return f'{_no(r.index)}{_play(r, c)}<span class="jk-chunks">{cards}</span>'
    return f'{_no(r.index)}{_play(r, c)}<span class="jk-src">{c.src(r.source)}</span>'


def _line_html(r: LineResult, c: _Ctx) -> str:
    if r.pending:
        return (f'<div class="jk-line jk-pending">{_head(r, c)}'
                f'<div class="jk-tr jk-wait"{c.ul}>{_t(c.ui, "pending")}</div></div>')
    if r.error:
        return f'<div class="jk-line">{_head(r, c)}<div class="jk-err"{c.ul}>⚠ {escape(r.error)}</div></div>'
    tail = "" if c.mode == MODE_SOURCE else _tr(r.tr, c)
    return f'<div class="jk-line">{_head(r, c)}{tail}</div>'


def _sentence_html(s: Sentence, lines: list[LineResult], c: _Ctx) -> str:
    group = lines[s.start - 1 : s.end]
    if s.start == s.end:
        return _line_html(group[0], c)
    heads = "".join(f'<div class="jk-line">{_head(r, c)}</div>' for r in group)
    tail = f'<div class="jk-err"{c.ul}>⚠ {escape(s.error)}</div>' if s.error else _tr(s.tr, c)
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
    if tts:
        classes.append("jk-tts")
    lang = f' data-lang="{escape(doc.lang)}" data-no-voice="{_t(opts.ui, "tts_no_voice")}"' if tts else ""
    lang += f' lang="{escape(doc.lang)}"'
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
        f"<h1 class=\"jk-title\" lang=\"{escape(doc.lang)}\">{escape(title)}</h1><div class=\"meta\">{escape(meta)}</div>"
        f"{_body(doc, mode, unit, opts, tts=False)}</body></html>"
    )


# 듣기: 어구(.jk-s)·줄(.jk-play)을 누르면 원문을 읽는다. 앱 화면(APP_JS)과 모바일 HTML이 같이 쓰는 함수 식으로,
# toast(msg)를 받아 {speak, stop, readAll}을 돌려준다.
# window.jkServerSay(text, line, el)가 있으면(앱) 서버 음성으로 넘기고, 없으면(모바일 HTML) 브라우저 음성으로 읽는다.
# 휠 클릭·Ctrl+클릭(폰에서는 길게 누르기)은 막지 않으므로 어구의 href 사전이 열린다.
TTS_JS = _asset("tts.js")

# 폰 폭에 맞추기: 원문 한 줄(끊어읽기 카드 묶음 또는 원문 줄)을 줄바꿈하지 않고, 넘치면 FIT_JS가 그 줄만
# 글자를 줄인다. 카드 여백·간격을 em으로 두어 글자와 함께 줄어든다. 모바일 HTML과 이미지가 같이 쓴다.
FIT_CSS = _asset("fit.css")

FIT_MIN = 0.6  # 이보다 더 줄여야 하는 줄은 줄이지 않고 두 줄로 넘긴다

# 넘치는 줄은 먼저 카드 여백·간격을 좁히고(jk-tight), 그래도 넘치면 글자 크기를 줄인다. 원래의 60%보다
# 작아져야 맞는 긴 줄은 줄이지 않고 원래 크기·간격으로 줄바꿈한다(jk-multi). 읽기와 쓰기를 줄 전체에 몰아서 해
# 레이아웃 계산을 줄인다. 숨어 있는 줄(다른 보기 방식)은 건너뛴다. 인자: document
FIT_JS = _asset("fit.js").replace("%MIN%", str(FIT_MIN))

MOBILE_CSS = _asset("mobile.css")

MOBILE_JS = _asset("mobile.js").replace("%FIT%", FIT_JS)  # %TTS%는 to_mobile_html이 채운다


def to_mobile_html(songs: list[tuple[Doc, str]], mode: str, unit: str, opts: ViewOptions | None,
                   title: str) -> str:
    """폰에서 읽기 좋은 단독 HTML. 곡이 여럿이면 한 파일로 묶고 한 번에 한 곡씩 보인다(⋮ 서랍에서 고름).

    songs: (문서, 곡 설명 한 줄). 보기 방식 세 가지를 모두 넣어 두고 위쪽 막대에서 바꾼다(처음은 mode).
    번역 가리기(누르면 하나씩 보임)·글자 크기도 막대에서 바꾸며, 고른 값은 그 브라우저에 기억한다.
    어구를 누르면 TTS로 읽고, 길게 누르면 브라우저 메뉴로 사전 링크를 열 수 있다.
    """
    opts = opts or ViewOptions()
    ui = opts.ui
    view = ViewOptions(opts.font_size, opts.show_numbers, False, opts.reading, opts.dictionary, ui)
    many = len(songs) > 1
    names = [escape(doc.title or _t(ui, "untitled")) for doc, _ in songs]
    langs = [escape(doc.lang) for doc, _ in songs]  # 곡 제목은 원문 언어 글꼴로
    drawer = ""
    if many:
        items = "".join(
            f'<li><a href="#song-{i}"><span class="jk-title" lang="{langs[i - 1]}">{i}. {names[i - 1]}</span>'
            f'<small>{sum(1 for s in doc.sources if s.strip())}{escape(_t(ui, "m_lines_suffix"))}</small></a></li>'
            for i, (doc, _) in enumerate(songs, 1))
        drawer = (f'<div class="m-drawer" id="m-drawer" aria-hidden="true"><div class="m-shade"></div>'
                  f'<nav class="m-panel" aria-label="{_t(ui, "m_toc")}"><div class="m-head"><b>{escape(title)}'
                  f'</b><button class="m-btn m-menu" type="button" data-act="close" '
                  f'aria-label="{_t(ui, "m_close")}">×</button></div><ol class="m-toc">{items}</ol></nav></div>')

    def nav(i: int) -> str:
        """곡 끝의 이전·다음 곡 버튼."""
        if not many:
            return ""
        gap = '<span class="m-gap"></span>'
        prev = (f'<a href="#song-{i - 1}"><small>‹ {_t(ui, "m_prev")}</small>'
                f'<span class="jk-title" lang="{langs[i - 2]}">{names[i - 2]}</span></a>' if i > 1 else gap)
        nxt = (f'<a class="m-next" href="#song-{i + 1}"><small>{_t(ui, "m_next")} ›</small>'
               f'<span class="jk-title" lang="{langs[i]}">{names[i]}</span></a>'
               if i < len(songs) else gap)
        return f'<div class="m-nav">{prev}{nxt}</div>'

    sections = []
    for i, (doc, meta) in enumerate(songs, 1):
        bodies = "".join(f'<div class="m-mode" data-mode="{m}">{_body(doc, m, unit, view)}</div>' for m in MODES)
        cur = " m-cur" if i == 1 else ""
        sections.append(f'<section class="m-song{cur}" id="song-{i}"><h2 class="jk-title" lang="{escape(doc.lang)}">{names[i - 1]}</h2>'
                        f'<div class="m-meta">{escape(meta)}</div>{bodies}{nav(i)}</section>')
    modes = "".join(f'<button class="m-btn" type="button" data-set-mode="{m}">{_t(ui, f"m_mode_{m}")}</button>'
                    for m in MODES)
    menu = (f'<button class="m-btn m-menu" type="button" data-act="menu" aria-label="{_t(ui, "m_toc")}">⋮</button>'
            if many else "")
    head = names[0] if many else escape(title)  # 여러 곡이면 지금 보는 곡 제목(MOBILE_JS가 바꾼다)
    book_lang = f' class="m-book jk-title" lang="{escape(songs[0][0].lang)}"' if songs else ' class="m-book"'
    bar = (f'<header class="m-bar"><div class="m-row"><div{book_lang}>{head}</div>'
           f'<button class="m-btn" type="button" data-act="smaller" aria-label="{_t(ui, "m_smaller")}">A−</button>'
           f'<button class="m-btn" type="button" data-act="bigger" aria-label="{_t(ui, "m_bigger")}">A+</button>{menu}'
           f'</div><div class="m-row m-acts">'
           f'<button class="m-btn" type="button" data-act="readall" aria-pressed="false">{_t(ui, "m_readall")}</button>'
           f'<button class="m-btn" type="button" data-act="echo" aria-pressed="false">{_t(ui, "m_echo")}</button>'
           f'<button class="m-btn" type="button" data-act="hide" aria-pressed="false">{_t(ui, "m_hide")}</button>'
           f'</div><div class="m-row"><div class="m-seg" role="group">{modes}</div></div></header>')
    fs = 15  # 폰 기본 글자 크기(px). A−·A+로 바꾼 값은 그 폰에 기억된다
    cls = ' class="m-many"' if many else ""
    return (
        f'<!doctype html><html lang="{ui}" data-mode="{mode}" data-fs="{fs}"{cls}><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        f"<title>{escape(title)}</title><style>{CSS}{MOBILE_CSS}{FIT_CSS}</style></head><body>"
        f"{bar}<main>{''.join(sections)}</main>{drawer}"
        f"<script>{MOBILE_JS.replace('%TTS%', TTS_JS)}</script></body></html>"
    )


IMAGE_WIDTHS = {"phone": 430, "wide": 820}

IMAGE_CSS = _asset("image.css")


def to_image_html(doc: Doc, mode: str, unit: str, opts: ViewOptions | None, title: str, meta: str,
                  width: str = "phone", dark: bool = False) -> str:
    """이미지로 저장할 조각 HTML. 브라우저가 이 조각을 SVG foreignObject로 그려 PNG로 만든다(app.IMAGE_JS).

    스타일이 모두 이 안에 들어 있어야 하고(이미지 안에서는 바깥 CSS를 못 쓴다), 글꼴은 시스템 글꼴만 쓴다.
    링크·TTS 속성은 빼고, 가린 번역도 풀어서 그린다.
    """
    opts = opts or ViewOptions()
    view = ViewOptions(opts.font_size, opts.show_numbers, False, opts.reading, DICT_OFF, opts.ui)
    w = IMAGE_WIDTHS.get(width, IMAGE_WIDTHS["phone"])
    colors = ({"%BG": "#161616", "%FG": "#ececec", "%CHIP": "#262626", "%CHIPLINE": "#3a3a3a", "%ACCENT": "#fb923c",
               "%SOFT": "rgba(251,146,60,.18)", "%ERR": "#ff8a80"} if dark else
              {"%BG": "#ffffff", "%FG": "#141414", "%CHIP": "#f3f3f3", "%CHIPLINE": "#dddddd", "%ACCENT": "#c2410c",
               "%SOFT": "rgba(234,88,12,.14)", "%ERR": "#b42318"})
    css = IMAGE_CSS.replace("%W", str(w))
    for k, v in colors.items():
        css = css.replace(k, v)
    return (f'<div class="jk-img"><style>{CSS}{FIT_CSS}{css}</style><h1 class="jk-title" lang="{escape(doc.lang)}">{escape(title)}</h1>'
            f'<div class="meta">{escape(meta)}</div>{_body(doc, mode, unit, view, tts=False)}'
            f'<div class="foot"><i></i><span>{escape(_t(opts.ui, "app_title"))}</span></div></div>')


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
