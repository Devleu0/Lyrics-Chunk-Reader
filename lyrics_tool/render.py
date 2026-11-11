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
.jk-play { display: inline-block; width: 1.6em; vertical-align: top; padding-top: .3em; font-size: .72em; opacity: .4;
           cursor: pointer; user-select: none; text-align: center; border-radius: 4px; }
.jk-play:hover, .jk-play:focus { opacity: 1; outline: none; }
.jk-tts .jk-chunks { max-width: calc(100% - 3.6em); }
.jk-tts.jk-nonum .jk-chunks { max-width: calc(100% - 1.3em); }
.jk-line.jk-reading > .jk-play, .jk-play.jk-speaking { opacity: 1; color: #e08600; }
.jk-line.jk-reading { background: rgba(255,170,0,.12); border-radius: 6px; box-shadow: 0 0 0 4px rgba(255,170,0,.12); }
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
            f'<span class="jk-t"{tab}>{escape(ch.t)}</span></span>'
            for ch in r.chunks
        )
        return f'{_no(r.index)}{_play(r, c)}<span class="jk-chunks">{cards}</span>'
    return f'{_no(r.index)}{_play(r, c)}<span class="jk-src">{c.src(r.source)}</span>'


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
    if tts:
        classes.append("jk-tts")
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


# 듣기: 어구(.jk-s)·줄(.jk-play)을 누르면 원문을 읽는다. 앱 화면(APP_JS)과 모바일 HTML이 같이 쓰는 함수 식으로,
# toast(msg)를 받아 {speak, stop, readAll}을 돌려준다.
# window.jkServerSay(text, line, el)가 있으면(앱) 서버 음성으로 넘기고, 없으면(모바일 HTML) 브라우저 음성으로 읽는다.
# 휠 클릭·Ctrl+클릭(폰에서는 길게 누르기)은 막지 않으므로 어구의 href 사전이 열린다.
TTS_JS = """(toast) => {
    const tts = window.speechSynthesis;
    const BCP47 = { en: 'en-US', ja: 'ja-JP', zh: 'zh-CN', ko: 'ko-KR', es: 'es-ES', fr: 'fr-FR', de: 'de-DE',
                    pt: 'pt-BR', it: 'it-IT', ru: 'ru-RU', vi: 'vi-VN', th: 'th-TH', id: 'id-ID' };
    const pickVoice = (lang) => {
        const base = lang.split('-')[0];
        const voices = tts.getVoices().filter(v => v.lang.replace('_', '-').toLowerCase().split('-')[0] === base);
        const score = (v) => (/natural|neural|online|google/i.test(v.name) ? 2 : 0)
                           + (v.lang.replace('_', '-').toLowerCase() === lang.toLowerCase() ? 1 : 0);
        return voices.sort((a, b) => score(b) - score(a))[0] || null;
    };
    tts?.getVoices();  // Chrome은 처음 부를 때 목록을 비동기로 채운다
    let current = null, run = 0;
    const mark = (el, on) => {
        if (!el) return;
        el.classList.toggle('jk-speaking', on);
        if (el.classList.contains('jk-play')) el.closest('.jk-line')?.classList.toggle('jk-reading', on);
    };
    const stop = () => {
        run++;
        tts?.cancel();
        window.jkServerStop?.();
        mark(current, false);
        current = null;
    };
    // 브라우저 음성으로 한 번 읽는다. 끝나면 done(ok) — 음성이 없으면 안내하고 false
    const speak = (el, text, done) => {
        const wrap = el.closest('.jk-wrap');
        const code = wrap?.dataset.lang || '';
        const lang = BCP47[code] || code;
        const none = wrap?.dataset.noVoice || `No voice for ${lang}`;
        if (!tts || typeof SpeechSynthesisUtterance === 'undefined') { toast(none); return done?.(false); }
        const voice = lang && pickVoice(lang);
        // 목록이 채워졌는데 맞는 음성이 없으면 기본 음성(다른 언어)으로 엉뚱하게 읽으므로 안내만 한다
        if (lang && !voice && tts.getVoices().length) { toast(none); return done?.(false); }
        const u = new SpeechSynthesisUtterance(text);
        if (lang) u.lang = lang;
        if (voice) u.voice = voice;
        u.rate = parseFloat(document.documentElement.dataset.rate || '1') || 1;
        const end = () => { mark(el, false); if (current === el) current = null; done?.(true); };
        u.onend = end;
        u.onerror = end;
        mark(el, true);
        current = el;
        tts.speak(u);
    };
    const say = (el, text, line) => {
        const wasSame = current === el;
        stop();
        if (wasSame) return;  // 읽는 중에 다시 누르면 멈춤
        if (window.jkServerSay) { current = el; mark(el, true); return window.jkServerSay(text, line, el); }
        speak(el, text);
    };
    // 서버 음성이 끝났을 때(앱) 표시를 지운다
    const done = (el) => { mark(el, false); if (current === el) current = null; };
    document.addEventListener('click', (e) => {
        const el = e.target.closest('.jk-s[data-tts], .jk-play');
        if (!el || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        say(el, el.dataset.tts, el.classList.contains('jk-play') ? el.dataset.line : '');
    });
    document.addEventListener('keydown', (e) => {
        const el = e.target.closest?.('.jk-play');
        if (el && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); el.click(); }
    });
    // 브라우저 음성으로 줄들을 차례로 읽는다(모바일 HTML의 '전체 듣기'). echo면 그 줄 길이만큼 쉬어 따라 해 볼 수 있게
    const readAll = (plays, echo, onDone) => {
        stop();
        const my = run;
        let i = 0;
        const next = () => {
            if (my !== run) return;
            if (i >= plays.length) return onDone?.();
            const el = plays[i++];
            el.scrollIntoView({ block: 'center', behavior: 'smooth' });
            const t0 = Date.now();
            speak(el, el.dataset.tts, (ok) => {
                if (my !== run) return;
                if (!ok) { stop(); return onDone?.(); }
                setTimeout(next, echo ? Date.now() - t0 + 500 : 450);
            });
        };
        next();
    };
    return { speak, stop, readAll, done };
}"""

# 폰 폭에 맞추기: 원문 한 줄(끊어읽기 카드 묶음 또는 원문 줄)을 줄바꿈하지 않고, 넘치면 FIT_JS가 그 줄만
# 글자를 줄인다. 카드 여백·간격을 em으로 두어 글자와 함께 줄어든다. 모바일 HTML과 이미지가 같이 쓴다.
FIT_CSS = """
.jk-line { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: start; }
.jk-nonum .jk-line { grid-template-columns: minmax(0, 1fr); }
.jk-tts .jk-line { grid-template-columns: auto auto minmax(0, 1fr); }
.jk-tts.jk-nonum .jk-line { grid-template-columns: auto minmax(0, 1fr); }
.jk-tts .jk-line > .jk-chunks, .jk-tts .jk-line > .jk-src { max-width: none; }
.jk-line > .jk-chunks, .jk-line > .jk-src { min-width: 0; max-width: none; overflow-x: auto; scrollbar-width: none; }
.jk-line > .jk-tr, .jk-line > .jk-err { grid-column: 1 / -1; margin-left: 0; padding-left: 2em; }
.jk-nonum .jk-line > .jk-tr, .jk-nonum .jk-line > .jk-err { padding-left: 0; }
.jk-chunks { flex-wrap: nowrap; gap: .3em; }
.jk-chunks::-webkit-scrollbar, .jk-src::-webkit-scrollbar { display: none; }
.jk-chunk { flex: 0 0 auto; padding: .2em .45em; white-space: nowrap; }
.jk-src { white-space: nowrap; }
.jk-chunks.jk-tight { gap: .12em; }
.jk-tight .jk-chunk { padding: .15em .22em; }
.jk-chunks.jk-multi { flex-wrap: wrap; overflow-x: visible; }
.jk-multi .jk-chunk { flex: 0 1 auto; min-width: 0; max-width: 100%; white-space: normal;
                     word-break: keep-all; overflow-wrap: anywhere; }
.jk-src.jk-multi { white-space: normal; overflow-x: visible; }
"""

FIT_MIN = 0.6  # 이보다 더 줄여야 하는 줄은 줄이지 않고 두 줄로 넘긴다

# 넘치는 줄은 먼저 카드 여백·간격을 좁히고(jk-tight), 그래도 넘치면 글자 크기를 줄인다. 원래의 60%보다
# 작아져야 맞는 긴 줄은 줄이지 않고 원래 크기·간격으로 줄바꿈한다(jk-multi). 읽기와 쓰기를 줄 전체에 몰아서 해
# 레이아웃 계산을 줄인다. 숨어 있는 줄(다른 보기 방식)은 건너뛴다. 인자: document
FIT_JS = """(doc) => {
    const MIN = %MIN%;
    const els = [...doc.querySelectorAll('.jk-chunks, .jk-wrap .jk-src')];
    els.forEach(el => { el.style.fontSize = ''; el.classList.remove('jk-tight', 'jk-multi'); });
    const over0 = els.filter(el => el.getClientRects().length && el.scrollWidth > el.clientWidth + 1);
    over0.forEach(el => el.classList.add('jk-tight'));
    const multi = (el) => { el.style.fontSize = ''; el.classList.remove('jk-tight'); el.classList.add('jk-multi'); };
    let todo = over0;
    const scale = new Map();
    for (let pass = 0; pass < 4 && todo.length; pass++) {
        const over = todo.map(el => [el, el.clientWidth, el.scrollWidth]).filter(([, c, w]) => w > c + 1);
        todo = [];
        over.forEach(([el, c, w]) => {
            const s = (scale.get(el) || 1) * (c / w) * 0.98;
            if (s < MIN && (pass > 0 || s < MIN * 0.95)) return multi(el);
            scale.set(el, Math.max(MIN, s));
            el.style.fontSize = Math.max(MIN, s) + 'em';
            todo.push(el);
        });
    }
    todo.filter(el => el.scrollWidth > el.clientWidth + 1).forEach(multi);  // 끝까지 넘치면 줄바꿈
}""".replace("%MIN%", str(FIT_MIN))

MOBILE_CSS = """
:root { color-scheme: light dark; --bg: #fff; --fg: #161616; --muted: #6b6b6b; --line: rgba(127,127,127,.22);
        --bar: rgba(255,255,255,.94); --on: #1a73e8; --on-fg: #fff; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #121212; --fg: #ececec; --muted: #9a9a9a; --bar: rgba(18,18,18,.94); --on: #8ab4f8; --on-fg: #111; }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--fg);
       font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic",
                    "Hiragino Sans", "Noto Sans JP", "Noto Sans SC", "Microsoft YaHei", sans-serif; }
.m-bar { position: sticky; top: 0; z-index: 10; background: var(--bar); backdrop-filter: blur(8px);
         -webkit-backdrop-filter: blur(8px); border-bottom: 1px solid var(--line);
         padding: 8px 12px; padding-top: max(8px, env(safe-area-inset-top)); }
.m-row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.m-row + .m-row { margin-top: 6px; }
.m-book { flex: 1 1 auto; min-width: 0; font-weight: 700; font-size: 15px; white-space: nowrap; overflow: hidden;
          text-overflow: ellipsis; }
.m-btn { font: inherit; font-size: 13px; color: inherit; background: transparent; border: 1px solid var(--line);
         border-radius: 999px; padding: 6px 11px; min-height: 34px; cursor: pointer; }
.m-btn[aria-pressed="true"] { background: var(--on); color: var(--on-fg); border-color: var(--on); }
.m-acts .m-btn { flex: 1 1 0; padding: 6px 4px; white-space: nowrap; }
.m-seg { display: flex; flex: 1 1 100%; }
.m-seg .m-btn { flex: 1 1 0; border-radius: 0; margin-left: -1px; padding: 6px 4px; }
.m-seg .m-btn:first-child { border-radius: 999px 0 0 999px; margin-left: 0; }
.m-seg .m-btn:last-child { border-radius: 0 999px 999px 0; }
main { max-width: 720px; margin: 0 auto; padding: 12px 14px calc(48px + env(safe-area-inset-bottom)); }
.m-tocbox { margin: 4px 0 20px; border: 1px solid var(--line); border-radius: 12px; scroll-margin-top: 96px; }
.m-tocbox > summary { padding: 10px 14px; font-weight: 700; font-size: 15px; cursor: pointer; }
.m-tocbox > summary small { color: var(--muted); font-weight: 400; }
.m-tocbox[open] > summary { border-bottom: 1px solid var(--line); }
.m-toc { margin: 0; padding: 0; list-style: none; }
.m-toc li + li { border-top: 1px solid var(--line); }
.m-toc a { display: flex; gap: 8px; padding: 9px 14px; font-size: 15px; color: inherit; text-decoration: none; }
.m-toc span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
a.m-book { color: inherit; text-decoration: none; }
.m-toc small { margin-left: auto; color: var(--muted); white-space: nowrap; }
.m-song { scroll-margin-top: 96px; }
.m-song + .m-song { margin-top: 36px; padding-top: 20px; border-top: 1px solid var(--line); }
.m-song h2 { font-size: 1.15em; margin: 0 0 2px; }
.m-meta { color: var(--muted); font-size: 12px; margin-bottom: 14px; }
.m-top { display: inline-block; margin-top: 8px; color: var(--muted); font-size: 13px; text-decoration: none;
         padding: 8px 0; }
.jk-wrap { font-size: var(--m-fs, 18px); line-height: 1.55; }
.jk-line { margin: 0 0 1em; }
.jk-tr, .jk-err { margin-left: 2em; }
.jk-no { min-width: 1.9em; }
.m-mode { display: none; }
html[data-mode="source"] .m-mode[data-mode="source"], html[data-mode="target"] .m-mode[data-mode="target"],
html[data-mode="both"] .m-mode[data-mode="both"] { display: block; }
html.m-hide .jk-t, html.m-hide .jk-tr { filter: blur(5px); transition: filter .15s; cursor: pointer; }
html.m-hide .m-shown { filter: none; }
"""

MOBILE_JS = """
(() => {
  const root = document.documentElement;
  const KEY = 'lyrics-jikdok-mobile';
  let prefs = {};
  try { prefs = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch {}
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch {} };
  const fs0 = parseInt(root.dataset.fs, 10) || 18;
  let apply = () => {
    root.dataset.mode = prefs.mode || root.dataset.mode;
    root.classList.toggle('m-hide', !!prefs.hide);
    root.style.setProperty('--m-fs', (prefs.fs || fs0) + 'px');
    document.querySelectorAll('[data-set-mode]').forEach(b =>
      b.setAttribute('aria-pressed', String(b.dataset.setMode === root.dataset.mode)));
    document.querySelector('[data-act="hide"]')?.setAttribute('aria-pressed', String(!!prefs.hide));
  };
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-set-mode], [data-act]');
    if (b) {
      if (b.dataset.setMode) prefs.mode = b.dataset.setMode;
      const act = b.dataset.act;
      if (act === 'hide') { prefs.hide = !prefs.hide; document.querySelectorAll('.m-shown').forEach(x => x.classList.remove('m-shown')); }
      if (act === 'bigger') prefs.fs = Math.min(32, (prefs.fs || fs0) + 1);
      if (act === 'smaller') prefs.fs = Math.max(12, (prefs.fs || fs0) - 1);
      save(); apply(); return;
    }
    const box = document.getElementById('m-toc');
    const goTo = (el) => {  // 위쪽 막대 높이만큼 비워 두고 옮긴다(글자 크기에 따라 막대 높이가 바뀐다)
      const bar = document.querySelector('.m-bar')?.offsetHeight || 0;
      scrollTo({ top: el.getBoundingClientRect().top + scrollY - bar - 8 });
    };
    const pick = box && e.target.closest('.m-toc a');
    if (pick) {  // 곡을 고르면 목차를 접고 그 곡으로 간다(접은 뒤에 옮겨야 위치가 맞는다)
      e.preventDefault();
      box.open = false;
      const id = pick.getAttribute('href').slice(1);
      const song = document.getElementById(id);
      if (song) goTo(song);
      history.replaceState(null, '', '#' + id);
      return;
    }
    if (box && e.target.closest('a[href="#m-toc"]')) {  // '↑ 목차'·위쪽 제목: 다시 펼친다
      e.preventDefault();
      box.open = true;
      goTo(box);
      return;
    }
    const gloss = root.classList.contains('m-hide') && e.target.closest('.jk-t, .jk-tr');
    if (gloss) gloss.classList.toggle('m-shown');  // 가린 뜻은 눌러서 하나씩 확인
  });
  const fit = """ + FIT_JS + """;
  let queued = false;
  const refit = () => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; fit(document); }); };
  const apply0 = apply;
  apply = () => { apply0(); refit(); };
  addEventListener('resize', refit);
  document.fonts?.ready.then(refit);
  apply();
  const toast = (msg) => {
    document.querySelector('#m-toast')?.remove();
    const d = Object.assign(document.createElement('div'), { id: 'm-toast', textContent: msg });
    d.style.cssText = 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:99;'
      + 'max-width:90vw;padding:10px 16px;border-radius:8px;background:rgba(30,30,30,.92);color:#fff;font-size:14px';
    document.body.appendChild(d);
    setTimeout(() => d.remove(), 3500);
  };
  const tts = (%TTS%)(toast);
  // 전체 듣기: 화면에 보이는 곡부터 그 곡의 줄을 차례로 읽는다. 다시 누르면 멈춤. '따라 말하기'면 줄마다 그 길이만큼 쉰다
  const readBtn = document.querySelector('[data-act="readall"]');
  const echoBtn = document.querySelector('[data-act="echo"]');
  let reading = false;
  const setReading = (on) => { reading = on; readBtn?.setAttribute('aria-pressed', String(on)); };
  echoBtn?.setAttribute('aria-pressed', String(!!prefs.echo));
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-act="readall"], [data-act="echo"]');
    if (!b) return;
    e.stopImmediatePropagation();
    if (b.dataset.act === 'echo') {
      prefs.echo = !prefs.echo; save(); b.setAttribute('aria-pressed', String(prefs.echo)); return;
    }
    if (reading) { tts.stop(); return setReading(false); }
    const songs = [...document.querySelectorAll('.m-song')];
    const song = songs.find(s => s.getBoundingClientRect().bottom > 120) || songs[0];
    const plays = [...song.querySelectorAll(`.m-mode[data-mode="${root.dataset.mode}"] .jk-play`)];
    setReading(true);
    tts.readAll(plays, !!prefs.echo, () => setReading(false));
  }, true);
})();
"""


def to_mobile_html(songs: list[tuple[Doc, str]], mode: str, unit: str, opts: ViewOptions | None,
                   title: str) -> str:
    """폰에서 읽기 좋은 단독 HTML. 곡이 여럿이면 목차가 붙는 한 파일로 묶는다.

    songs: (문서, 곡 설명 한 줄). 보기 방식 세 가지를 모두 넣어 두고 위쪽 막대에서 바꾼다(처음은 mode).
    번역 가리기(누르면 하나씩 보임)·글자 크기도 막대에서 바꾸며, 고른 값은 그 브라우저에 기억한다.
    어구를 누르면 TTS로 읽고, 길게 누르면 브라우저 메뉴로 사전 링크를 열 수 있다.
    """
    opts = opts or ViewOptions()
    ui = opts.ui
    view = ViewOptions(opts.font_size, opts.show_numbers, False, opts.reading, opts.dictionary, ui)
    many = len(songs) > 1
    toc = ""
    if many:
        items = "".join(
            f'<li><a href="#song-{i}"><span>{i}. {escape(doc.title or _t(ui, "untitled"))}</span>'
            f'<small>{sum(1 for s in doc.sources if s.strip())}{escape(_t(ui, "m_lines_suffix"))}</small></a></li>'
            for i, (doc, _) in enumerate(songs, 1))
        # 처음엔 펼쳐 두고, 곡을 고르면 접는다. 곡 끝의 '↑ 목차'나 위쪽 제목을 누르면 다시 펼친다(MOBILE_JS)
        count = _t(ui, "m_toc_count", n=len(songs))
        toc = (f'<details class="m-tocbox" id="m-toc" open><summary>{_t(ui, "m_toc")} <small>· {count}</small>'
               f'</summary><ol class="m-toc">{items}</ol></details>')
    sections = []
    for i, (doc, meta) in enumerate(songs, 1):
        bodies = "".join(f'<div class="m-mode" data-mode="{m}">{_body(doc, m, unit, view)}</div>' for m in MODES)
        back = f'<a class="m-top" href="#m-toc">↑ {_t(ui, "m_toc")}</a>' if many else ""
        sections.append(f'<section class="m-song" id="song-{i}"><h2>{escape(doc.title or _t(ui, "untitled"))}</h2>'
                        f'<div class="m-meta">{escape(meta)}</div>{bodies}{back}</section>')
    modes = "".join(f'<button class="m-btn" type="button" data-set-mode="{m}">{_t(ui, f"m_mode_{m}")}</button>'
                    for m in MODES)
    book = (f'<a class="m-book" href="#m-toc">{escape(title)}</a>' if many
            else f'<div class="m-book">{escape(title)}</div>')
    bar = (f'<header class="m-bar"><div class="m-row">{book}'
           f'<button class="m-btn" type="button" data-act="smaller" aria-label="{_t(ui, "m_smaller")}">A−</button>'
           f'<button class="m-btn" type="button" data-act="bigger" aria-label="{_t(ui, "m_bigger")}">A+</button>'
           f'</div><div class="m-row m-acts">'
           f'<button class="m-btn" type="button" data-act="readall" aria-pressed="false">{_t(ui, "m_readall")}</button>'
           f'<button class="m-btn" type="button" data-act="echo" aria-pressed="false">{_t(ui, "m_echo")}</button>'
           f'<button class="m-btn" type="button" data-act="hide" aria-pressed="false">{_t(ui, "m_hide")}</button>'
           f'</div><div class="m-row"><div class="m-seg" role="group">{modes}</div></div></header>')
    fs = max(int(opts.font_size), 17)
    return (
        f'<!doctype html><html lang="{ui}" data-mode="{mode}" data-fs="{fs}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        f"<title>{escape(title)}</title><style>{CSS}{MOBILE_CSS}{FIT_CSS}</style></head><body>"
        f"{bar}<main>{toc}{''.join(sections)}</main>"
        f"<script>{MOBILE_JS.replace('%TTS%', TTS_JS)}</script></body></html>"
    )


IMAGE_WIDTHS = {"phone": 430, "wide": 820}

IMAGE_CSS = """
.jk-img { box-sizing: border-box; width: %Wpx; padding: 28px 22px 20px; background: %BG; color: %FG;
          font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic",
                       "Hiragino Sans", "Yu Gothic", "Noto Sans JP", "Noto Sans SC", "Microsoft YaHei", sans-serif; }
.jk-img * { box-sizing: border-box; }
.jk-img h1 { font-size: 21px; line-height: 1.3; margin: 0 0 4px; }
.jk-img .meta { font-size: 12px; opacity: .6; margin: 0 0 20px; }
.jk-img .foot { font-size: 11px; opacity: .45; margin-top: 16px; text-align: right; }
.jk-img .jk-chunk { background: %CHIP; border-color: %CHIPLINE; }
"""


def to_image_html(doc: Doc, mode: str, unit: str, opts: ViewOptions | None, title: str, meta: str,
                  width: str = "phone", dark: bool = False) -> str:
    """이미지로 저장할 조각 HTML. 브라우저가 이 조각을 SVG foreignObject로 그려 PNG로 만든다(app.IMAGE_JS).

    스타일이 모두 이 안에 들어 있어야 하고(이미지 안에서는 바깥 CSS를 못 쓴다), 글꼴은 시스템 글꼴만 쓴다.
    링크·TTS 속성은 빼고, 가린 번역도 풀어서 그린다.
    """
    opts = opts or ViewOptions()
    view = ViewOptions(opts.font_size, opts.show_numbers, False, opts.reading, DICT_OFF, opts.ui)
    w = IMAGE_WIDTHS.get(width, IMAGE_WIDTHS["phone"])
    colors = ({"%BG": "#161616", "%FG": "#ececec", "%CHIP": "#262626", "%CHIPLINE": "#3a3a3a"} if dark else
              {"%BG": "#ffffff", "%FG": "#141414", "%CHIP": "#f3f3f3", "%CHIPLINE": "#dddddd"})
    css = IMAGE_CSS.replace("%W", str(w))
    for k, v in colors.items():
        css = css.replace(k, v)
    return (f'<div class="jk-img"><style>{CSS}{FIT_CSS}{css}</style><h1>{escape(title)}</h1>'
            f'<div class="meta">{escape(meta)}</div>{_body(doc, mode, unit, view, tts=False)}'
            f'<div class="foot">{escape(_t(opts.ui, "app_title"))}</div></div>')


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
