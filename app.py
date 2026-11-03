"""Lyrics Chunk Reader (가사 직독직해) — Gradio 웹 UI.

실행: python app.py  →  http://127.0.0.1:7860
같은 와이파이의 폰에서 쓰려면: HOST=0.0.0.0 python app.py → http://<PC의 IP>:7860

화면 문구는 lyrics_tool.i18n(영어·한국어)에서 가져온다. 처음에는 브라우저 언어를 따르고,
머리말의 언어 버튼으로 바꾸면 모든 라벨을 다시 그린다(relabel).
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from pathlib import Path

import gradio as gr
import pandas as pd

from lyrics_tool.backends import (
    BACKENDS, GEMINI_DEFAULT_MODEL, OLLAMA_DEFAULT_MODEL, BackendError, OllamaBackend, make_backend,
)
from lyrics_tool.cache import Cache, default_title
from lyrics_tool.cleanup import clean_lyrics, read_lyrics_file
from lyrics_tool.history import History, import_from_cache
from lyrics_tool.core import (
    Doc, EditError, LineNotFound, Translator, apply_edit, chunks_to_text, sentence_of, text_to_chunks,
)
from lyrics_tool.i18n import UI_LANGS, pick_ui, t
from lyrics_tool.langs import LANGS, detect_language, lang_name
from lyrics_tool.reading import DICT_INTL, DICT_NAVER, DICTS
from lyrics_tool.render import (
    MODE_SOURCE, MODES, UNIT_LINE, UNITS, ViewOptions, mode_label, to_html, to_markdown, to_print_html, unit_label,
)

APP_NAME = "Lyrics Chunk Reader"

DEFAULT_SETTINGS = {
    "ui": "", "target": "",  # 비어 있으면 브라우저 언어로 정한다
    "engine": "ollama", "model": "", "base_url": "", "batch": 8, "retries": 3,
    "mode": MODE_SOURCE, "unit": UNIT_LINE, "font": 16, "numbers": True, "hide": False,
    "reading": True, "dict": "",
    "fb_engine": "none", "fb_model": "", "auto_clean": True,
}

CACHE: Cache | None = None
HISTORY: History | None = None


def _load_dotenv() -> None:
    """python-dotenv 없이 .env를 읽는다 (이미 설정된 환경변수는 덮지 않음)."""
    env = Path(__file__).with_name(".env")
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def get_cache() -> Cache:
    global CACHE
    if CACHE is None:
        CACHE = Cache(Path(os.environ.get("LYRICS_CACHE") or Path.home() / ".lyrics-jikdok" / "cache.db").expanduser())
    return CACHE


def get_history() -> History:
    """곡마다 JSON 파일로 저장하는 번역 히스토리. 처음 열 때 예전 버전의 히스토리를 옮긴다."""
    global HISTORY
    if HISTORY is None:
        HISTORY = History()
        import_from_cache(get_cache(), HISTORY)
    return HISTORY


def make_translator(engine, model, api_key, base_url, batch, retries, target, ui) -> Translator:
    backend = make_backend(engine, (model or "").strip(), (api_key or "").strip(), (base_url or "").strip(),
                           int(retries), ui)
    return Translator(backend, batch_size=int(batch), cache=get_cache(), target=target, ui=ui)


def make_fallback(fb_engine, fb_model, engine, api_key, base_url, batch, retries, target, ui) -> Translator | None:
    """보조 엔진. 주 엔진과 종류가 같으면 화면의 키·주소를, 다르면 .env 값을 쓴다."""
    if not fb_engine or fb_engine == "none":
        return None
    same = fb_engine == engine
    return make_translator(fb_engine, fb_model, api_key if same else "", base_url if same else "", batch, retries,
                           target, ui)


def _view(mode, unit, font, numbers, hide, reading, dictionary, ui):
    return mode, unit, ViewOptions(font_size=int(font), show_numbers=bool(numbers), hide_translation=bool(hide),
                                   reading=bool(reading), dictionary=dictionary or DICT_INTL, ui=ui or "en")


# ---------------------------------------------------------------- 선택지 (UI 언어별)


def engine_hint(engine: str, ui: str) -> tuple[str, str, bool]:
    """(모델 칸 안내, 서버 주소 안내, API 키 필요 여부)"""
    if engine == "ollama":
        return t(ui, "model_info_ollama", model=OLLAMA_DEFAULT_MODEL), t(ui, "url_ph_ollama"), False
    if engine == "gemini":
        return t(ui, "model_info_gemini", model=GEMINI_DEFAULT_MODEL), "", True
    return t(ui, "model_info_openai"), t(ui, "url_ph_openai"), True


def engine_choices(ui):
    return [(t(ui, f"engine_{k}"), k) for k in BACKENDS]


def fallback_choices(ui):
    return [(t(ui, "none"), "none")] + engine_choices(ui)


def source_choices(ui):
    return [(t(ui, "auto_detect"), "auto")] + [(lang_name(c, ui), c) for c in LANGS]


def target_choices(ui):
    return [(t(ui, "to_lang", lang=lang_name(c, ui)), c) for c in LANGS]


def mode_choices(ui):
    return [(mode_label(m, ui), m) for m in MODES]


def unit_choices(ui):
    return [(unit_label(u, ui), u) for u in UNITS]


def dict_choices(ui):
    return [(t(ui, f"dict_{d}"), d) for d in DICTS]


# ---------------------------------------------------------------- 공통 출력


def _status(doc: Doc, tr: Translator, note: str = "") -> str:
    return _status_line(doc, tr.ui, tr.backend.name, tr.backend.model, note)


def _status_line(doc: Doc, ui: str, engine_name: str, model: str, note: str = "") -> str:
    done, total = doc.progress()
    lines = doc.lines()
    n = sum(1 for r in lines if not r.blank)
    failed = sum(1 for r in lines if r.error)
    parts = [f"**{doc.title}**" if doc.title else "",
             f"{lang_name(doc.lang, ui)} → {lang_name(doc.target, ui)}", t(ui, "n_lines", n=n),
             t(ui, "segments", done=done, total=total),
             t(ui, "engine_status", name=engine_name, model=model) if model else ""]
    if failed:
        parts.append(t(ui, "failed_lines", n=failed))
    return " · ".join(p for p in parts if p) + (f"\n\n{note}" if note else "")


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_")[:40] or "lyrics"


def _export(doc: Doc | None, mode, unit, opts: ViewOptions) -> list[str] | None:
    if doc is None:
        return None
    out_dir = Path(tempfile.gettempdir()) / "lyrics-jikdok"
    out_dir.mkdir(exist_ok=True)
    base = _safe(doc.title)
    tag = mode if mode == MODE_SOURCE else f"{mode}-{unit}"
    md = out_dir / f"{base}_{tag}.md"
    html = out_dir / f"{base}_{tag}_print.html"
    js = out_dir / f"{base}_data.json"
    ui = opts.ui
    md.write_text(to_markdown(doc, mode, unit, opts), encoding="utf-8")
    meta = (f"{lang_name(doc.lang, ui)} → {lang_name(doc.target, ui)} · {mode_label(mode, ui)} · "
            f"{unit_label(unit, ui)}")
    html.write_text(to_print_html(doc, mode, unit, opts, doc.title or t(ui, "app_title"), meta), encoding="utf-8")
    js.write_text(doc.to_json(), encoding="utf-8")
    return [str(md), str(html), str(js)]


def history_dir_label() -> str:
    """화면에 보일 히스토리 폴더. 프로젝트 안이면 상대 경로, 아니면 홈을 ~로 줄인다."""
    d = get_history().dir.resolve()
    for base, prefix in ((Path(__file__).resolve().parent, ""), (Path.home(), "~/")):
        try:
            return prefix + d.relative_to(base).as_posix() + "/"
        except ValueError:
            continue
    return str(d)


def history_view(ui, current_title=""):
    """(표, 행별 id, 히스토리 칸 update)"""
    entries = get_history().list()
    cols = [t(ui, k) for k in ("col_title", "col_langs", "col_lines", "col_model", "col_saved")]
    rows = [[e.title, f"{lang_name(e.lang, ui)} → {lang_name(e.target, ui)}", e.lines, e.model, e.when]
            for e in entries]
    label = t(ui, "history_current", n=len(entries), title=current_title) if current_title \
        else t(ui, "history_count", n=len(entries))
    return (gr.update(value=pd.DataFrame(rows, columns=cols), visible=bool(entries)), [e.id for e in entries],
            gr.update(label=label), gr.update(visible=not entries))


def _save_history(doc: Doc, engine, model, batch, ui) -> str:
    """끝까지 번역됐으면 저장하고 상태 줄에 붙일 안내를 돌려준다."""
    if get_history().save(doc, engine, model, batch):
        return t(ui, "history_saved")
    return t(ui, "history_not_saved") if not doc.pending_keys() else ""


# ---------------------------------------------------------------- 입력 정리


def _clean(lyrics, lang, target, ui):
    # 섞여 있는 한국어 번역 줄은 한국어로 번역할 때만 지운다 (한국어 가사를 지우지 않게)
    return clean_lyrics(lyrics or "", ui, drop_hangul=target == "ko" and lang != "ko")


def clean_text(lyrics, lang, target, ui):
    text, report = _clean(lyrics, lang, target, ui)
    msg = t(ui, "cleaned", items=", ".join(report)) if report else t(ui, "nothing_to_clean")
    return text, msg


def load_file(path, lang, target, ui):
    if not path:
        return gr.update(), gr.update(), ""
    text, report = _clean(read_lyrics_file(path), lang, target, ui)
    msg = t(ui, "file_loaded", name=Path(path).name)
    if report:
        msg += "\n\n" + t(ui, "cleaned", items=", ".join(report))
    return text, Path(path).stem, msg


# ---------------------------------------------------------------- 번역 (점진 표시)


def run_translate(lyrics, title, lang, target, auto_clean, engine, model, api_key, base_url, batch, retries,
                  fb_engine, fb_model, force, *view):
    mode, unit, opts = _view(*view)
    ui = opts.ui
    if not lyrics or not lyrics.strip():
        raise gr.Error(t(ui, "err_no_lyrics"))
    notes = []
    if auto_clean:
        lyrics, report = _clean(lyrics, lang, target, ui)
        if report:
            notes.append(t(ui, "cleaned", items=", ".join(report)))
    src = detect_language(lyrics) if lang == "auto" else lang
    if src == target:
        raise gr.Error(t(ui, "err_same_lang", lang=lang_name(src, ui)))

    tr = make_translator(engine, model, api_key, base_url, batch, retries, target, ui)
    doc = tr.prepare(lyrics, src, use_cache=not force)
    doc.title = (title or "").strip() or default_title(lyrics, t(ui, "untitled"))
    cached, _ = doc.progress()
    if cached:
        notes.append(t(ui, "cache_hits", n=cached))
    note = "\n\n".join(notes)
    yield lyrics, to_html(doc, mode, unit, opts), _status(doc, tr, note or t(ui, "translating")), doc, None

    try:
        for doc in tr.run(doc):
            yield gr.update(), to_html(doc, mode, unit, opts), _status(doc, tr, t(ui, "translating")), doc, None

        fb = make_fallback(fb_engine, fb_model, engine, api_key, base_url, batch, retries, target, ui)
        failed = sum(1 for r in doc.lines() if r.error)
        if fb and failed:
            for doc in fb.retry_failed(doc):
                yield (gr.update(), to_html(doc, mode, unit, opts),
                       _status(doc, tr, t(ui, "fb_retrying", name=fb.backend.name, model=fb.backend.model)),
                       doc, None)
            fixed = failed - sum(1 for r in doc.lines() if r.error)
            notes.append(t(ui, "fb_done", fixed=fixed, failed=failed))
    except BackendError as e:
        notes.append(f"⚠ {e}")
    notes.append(_save_history(doc, engine, tr.backend.model, batch, ui))
    yield gr.update(), to_html(doc, mode, unit, opts), _status(doc, tr, "\n\n".join(n for n in notes if n)), doc, \
        _export(doc, mode, unit, opts)


def rerender(doc, *view):
    mode, unit, opts = _view(*view)
    return to_html(doc, mode, unit, opts), _export(doc, mode, unit, opts)


# ---------------------------------------------------------------- 줄 수정


def _edit_fields(doc: Doc | None, line_no, ui):
    """(안내, 청크, 줄 직역, 문장 직역 update)"""
    empty = ("", "", gr.update(visible=False, value=""))
    if doc is None or not line_no:
        return (t(ui, "err_run_first"),) + empty
    line_no = int(line_no)
    try:
        doc.locate(line_no)
    except LineNotFound:
        return ("⚠ " + t(ui, "line_not_target", n=line_no),) + empty
    r = doc.lines()[line_no - 1]
    if r.pending:
        return (t(ui, "line_pending", n=line_no, src=r.source),) + empty
    s = sentence_of(doc, line_no)
    info = t(ui, "line_head", n=line_no, src=r.source)
    if r.error:
        info += f"\n\n⚠ {r.error}"
    sent = gr.update(visible=False, value="")
    if s.end > s.start:
        info += "\n\n" + t(ui, "line_grouped", a=s.start, b=s.end)
        sent = gr.update(visible=True, value=s.tr, label=t(ui, "sent_tr_range", a=s.start, b=s.end))
    return info, chunks_to_text(r.chunks), r.tr, sent


def open_editor(doc, line_no, ui):
    return (*_edit_fields(doc, line_no, ui), gr.update(open=True))


def retranslate_line(doc, line_no, engine, model, api_key, base_url, batch, retries, *view):
    mode, unit, opts = _view(*view)
    ui = opts.ui
    if doc is None or not line_no:
        raise gr.Error(t(ui, "err_run_first_line"))
    tr = make_translator(engine, model, api_key, base_url, batch, retries, doc.target, ui)
    try:
        tr.retranslate(doc, int(line_no))
    except LineNotFound as e:
        raise gr.Error(t(ui, "line_not_target", n=int(line_no))) from e
    except BackendError as e:
        raise gr.Error(str(e)) from e
    note = t(ui, "retranslated", n=int(line_no))
    saved = _save_history(doc, engine, tr.backend.model, batch, ui)
    return (to_html(doc, mode, unit, opts), _status(doc, tr, f"{note} {saved}".strip()), doc,
            _export(doc, mode, unit, opts), *_edit_fields(doc, line_no, ui))


def save_line(doc, line_no, chunk_text, line_tr, sent_tr, engine, model, batch, *view):
    mode, unit, opts = _view(*view)
    ui = opts.ui
    if doc is None or not line_no:
        raise gr.Error(t(ui, "err_run_first_line"))
    try:
        apply_edit(doc, int(line_no), text_to_chunks(chunk_text), line_tr, sent_tr, cache=get_cache())
    except LineNotFound as e:
        raise gr.Error(t(ui, "line_not_target", n=int(line_no))) from e
    except EditError as e:
        raise gr.Error(t(ui, e.args[0])) from e
    gr.Info(t(ui, "saved", n=int(line_no)))
    get_history().save(doc, engine, make_backend(engine, (model or "").strip()).model, batch)
    return to_html(doc, mode, unit, opts), doc, _export(doc, mode, unit, opts)


def retry_all(doc, engine, model, api_key, base_url, batch, retries, *view):
    mode, unit, opts = _view(*view)
    ui = opts.ui
    if doc is None:
        raise gr.Error(t(ui, "err_run_first"))
    tr = make_translator(engine, model, api_key, base_url, batch, retries, doc.target, ui)
    try:
        for doc in tr.retry_failed(doc):
            yield to_html(doc, mode, unit, opts), _status(doc, tr, t(ui, "retrying")), doc, None
    except BackendError as e:
        yield to_html(doc, mode, unit, opts), _status(doc, tr, f"⚠ {e}"), doc, _export(doc, mode, unit, opts)
        return
    note = f"{t(ui, 'retry_done')} {_save_history(doc, engine, tr.backend.model, batch, ui)}".strip()
    yield to_html(doc, mode, unit, opts), _status(doc, tr, note), doc, _export(doc, mode, unit, opts)


# ---------------------------------------------------------------- 엔진 설정


def _engine_visibility(engine, ui):
    _, url_ph, needs_key = engine_hint(engine, ui)
    return gr.update(visible=needs_key), gr.update(visible=bool(url_ph), placeholder=url_ph)


def on_engine_change(engine, ui):
    """사용자가 엔진을 바꿨을 때만 호출(input 이벤트) — 저장된 설정 복원과 겹치지 않게."""
    models = OllamaBackend(model="", host=os.environ.get("OLLAMA_HOST", "http://localhost:11434")).list_models() \
        if engine == "ollama" else []
    key_u, url_u = _engine_visibility(engine, ui)
    return (gr.update(choices=models, value="", info=engine_hint(engine, ui)[0]),
            gr.update(value="", visible=key_u["visible"]),
            gr.update(value="", visible=url_u["visible"], placeholder=url_u["placeholder"]))


def check_engine(engine, model, api_key, base_url, ui):
    backend = make_backend(engine, (model or "").strip(), (api_key or "").strip(), (base_url or "").strip(), ui=ui)
    r = backend.check()
    icon = "✅" if r.ok else "⚠"
    more = "\n\n" + t(ui, "models_loaded", n=len(r.models)) if r.models else ""
    return f"{icon} {r.message}{more}", gr.update(choices=r.models[:200])


def clear_cache(ui):
    gr.Info(t(ui, "cache_cleared", n=get_cache().clear()))


# ---------------------------------------------------------------- 최근 번역


def open_history(ids, ui, mode, unit, font, numbers, hide, reading, dictionary, evt: gr.SelectData):
    """표에서 고른 곡을 저장된 결과 그대로 연다. 엔진을 부르지 않는다."""
    mode, unit, opts = _view(mode, unit, font, numbers, hide, reading, dictionary, ui)
    row = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
    if row is None or row >= len(ids):
        raise gr.Error(t(ui, "history_missing"))
    try:
        doc, meta = get_history().load(ids[row])
    except (OSError, KeyError, ValueError) as e:
        raise gr.Error(t(ui, "history_missing")) from e
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(meta.get("saved", 0)))
    kind = meta.get("engine", "")
    status = _status_line(doc, ui, t(ui, f"engine_{kind}") if kind in BACKENDS else kind, meta.get("model", ""),
                          t(ui, "history_opened", when=when))
    n = sum(1 for line in doc.sources if line.strip())
    return (to_html(doc, mode, unit, opts), status, doc, _export(doc, mode, unit, opts), ids[row],
            meta.get("lyrics", "\n".join(doc.sources)), doc.title, doc.lang, doc.target,
            gr.update(open=False, label=t(ui, "input_collapsed", name=doc.title, n=n)),
            gr.update(open=False, label=t(ui, "history_current", n=len(ids), title=doc.title)))


def delete_history(entry_id, ui):
    if not entry_id:
        raise gr.Error(t(ui, "history_pick"))
    get_history().delete(entry_id)
    gr.Info(t(ui, "history_deleted"))
    return None


# ---------------------------------------------------------------- 설정 기억


def restore_settings(saved, request: gr.Request):
    s = {**DEFAULT_SETTINGS, **(saved or {})}
    headers = getattr(request, "headers", None) or {}
    if s["ui"] not in ("en", "ko"):
        s["ui"] = pick_ui(headers.get("accept-language"))
    ui = s["ui"]
    if s["target"] not in LANGS:
        s["target"] = "ko" if ui == "ko" else "en"
    if s["engine"] not in BACKENDS:
        s["engine"] = DEFAULT_SETTINGS["engine"]
    if s["mode"] not in MODES:  # 예전 버전은 화면 이름을 저장했다
        s["mode"] = MODE_SOURCE
    if s["unit"] not in UNITS:
        s["unit"] = UNIT_LINE
    if s["dict"] not in DICTS:
        s["dict"] = DICT_NAVER if s["target"] == "ko" else DICT_INTL
    key_u, url_u = _engine_visibility(s["engine"], ui)
    return (ui, s["target"], s["engine"], gr.update(value=s["model"], info=engine_hint(s["engine"], ui)[0]), key_u,
            gr.update(value=s["base_url"], visible=url_u["visible"], placeholder=url_u["placeholder"]),
            s["batch"], s["retries"], s["mode"], s["unit"], s["font"], s["numbers"], s["hide"], s["reading"],
            s["dict"], s["fb_engine"], s["fb_model"], s["auto_clean"])


def save_settings(ui, target, engine, model, base_url, batch, retries, mode, unit, font, numbers, hide, reading,
                  dictionary, fb_engine, fb_model, auto_clean):
    # API 키는 브라우저에 저장하지 않는다 (.env 사용 권장)
    return dict(ui=ui, target=target, engine=engine, model=model or "", base_url=base_url or "", batch=batch,
                retries=retries, mode=mode, unit=unit, font=font, numbers=numbers, hide=hide, reading=reading,
                dict=dictionary, fb_engine=fb_engine, fb_model=fb_model or "", auto_clean=auto_clean)


# ---------------------------------------------------------------- 화면

APP_CSS = """
.gradio-container { overflow: clip !important; }  /* hidden이면 툴바 sticky가 동작하지 않는다 */
#jk-main { max-width: 1000px; margin: 0 auto; width: 100%; }
#jk-header { align-items: flex-start; flex-wrap: nowrap; }
#jk-header > :first-child { flex: 1 1 auto !important; min-width: 0 !important; }
#jk-header > :last-child { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; }
#jk-head h2 { margin: 0 0 2px; }
#jk-head p { margin: 0; opacity: .7; font-size: .9em; }
#jk-toolbar { position: sticky; top: 0; z-index: 20; background: var(--body-background-fill);
              padding: 6px 2px; border-bottom: 1px solid var(--border-color-primary);
              gap: 6px 12px; align-items: center; flex-wrap: wrap; }
#jk-toolbar > *, #jk-input-opts > * { flex: 0 1 auto !important; width: auto !important; min-width: 0 !important;
                                      max-width: 100%; }  /* 폰에서 라디오 묶음이 넘치지 않고 줄바꿈 */
#jk-input-opts { flex-wrap: wrap; gap: 6px 12px; align-items: center; }
#jk-status { font-size: .85em; opacity: .85; min-height: 1.4em; }
#jk-status p { margin: 2px 0; }
#jk-viewer { padding: 4px 2px 64px; }
"""

# 뷰어의 줄 번호를 누르면 오른쪽 '줄 수정'에 그 줄을 불러온다. Ctrl/Cmd+Enter로 번역.
APP_JS = """() => {
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            const b = document.querySelector('#jk-translate');
            if (b) { e.preventDefault(); b.click(); }
        }
    });
    document.addEventListener('click', (e) => {
        const no = e.target.closest('.jk-no');
        const input = document.querySelector('#jk-line-no input');
        if (!no || !input) return;
        input.value = no.textContent.trim();
        input.dispatchEvent(new Event('input', { bubbles: true }));
        setTimeout(() => document.querySelector('#jk-load-line')?.click(), 80);
    });
}"""


def collapse_input(lyrics, title, ui):
    """번역을 시작하면 입력 칸과 히스토리 칸을 접어 뷰어를 넓힌다. 접힌 제목에 곡 이름과 줄 수를 보여 준다."""
    text = (lyrics or "").strip()
    if not text:
        return gr.update(open=True, label=t(ui, "input")), gr.update()
    n = sum(1 for line in text.splitlines() if line.strip())
    name = (title or "").strip() or default_title(text, t(ui, "untitled"))
    return gr.update(open=False, label=t(ui, "input_collapsed", name=name, n=n)), gr.update(open=False)


def _head_md(ui):
    return f"## 🎧 {t(ui, 'app_title')}\n{t(ui, 'subtitle')}"


def build_ui() -> gr.Blocks:
    default_engine = os.environ.get("LYRICS_BACKEND", "ollama")
    if default_engine not in BACKENDS:
        default_engine = "ollama"
    DEFAULT_SETTINGS["engine"] = default_engine
    ui0 = "en"  # 처음 그리는 언어. 불러온 뒤 restore_settings가 브라우저 언어로 바꾼다
    model_info, url_ph, needs_key = engine_hint(default_engine, ui0)

    # UI 언어가 바뀌면 다시 그릴 것: (컴포넌트, ui·엔진 → gr.update)
    relabels: list[tuple[gr.components.Component, callable]] = []

    def L(comp, **keys):
        """keys: 속성 → i18n 키(문자열) 또는 ui를 받는 함수."""
        def upd(ui, engine):
            return gr.update(**{attr: (k(ui) if callable(k) else t(ui, k)) for attr, k in keys.items()})
        relabels.append((comp, upd))
        return comp

    with gr.Blocks(title=APP_NAME, analytics_enabled=False) as demo:  # Gradio 사용 통계 전송 끔
        doc_state = gr.State(None)
        settings = gr.BrowserState(DEFAULT_SETTINGS, storage_key="lyrics-jikdok-settings")

        # ---- 왼쪽: 설정 (자주 바꾸지 않는 것)
        with L(gr.Sidebar(label=t(ui0, "settings"), open=False, width=340), label="settings"):
            with L(gr.Accordion(t(ui0, "acc_engine"), open=True), label="acc_engine"):
                engine = L(gr.Radio(engine_choices(ui0), value=default_engine, label=t(ui0, "engine")),
                           label="engine", choices=engine_choices)
                model = gr.Dropdown([], value="", label=t(ui0, "model"), info=model_info, allow_custom_value=True)
                relabels.append((model, lambda ui, eng: gr.update(label=t(ui, "model"), info=engine_hint(eng, ui)[0])))
                api_key = L(gr.Textbox(label=t(ui0, "api_key"), type="password", visible=needs_key), label="api_key")
                base_url = gr.Textbox(label=t(ui0, "base_url"), placeholder=url_ph, visible=bool(url_ph))
                relabels.append((base_url, lambda ui, eng: gr.update(label=t(ui, "base_url"),
                                                                     placeholder=engine_hint(eng, ui)[1])))
                with gr.Row():
                    check_btn = L(gr.Button(t(ui0, "check"), size="sm"), value="check")
                    clear_btn = L(gr.Button(t(ui0, "clear_cache"), size="sm"), value="clear_cache")
                check_msg = gr.Markdown()
                batch = L(gr.Slider(1, 20, value=8, step=1, label=t(ui0, "batch"), info=t(ui0, "batch_info")),
                          label="batch", info="batch_info")
                retries = L(gr.Slider(0, 10, value=3, step=1, label=t(ui0, "retries"), info=t(ui0, "retries_info")),
                            label="retries", info="retries_info")
                fb_engine = L(gr.Dropdown(fallback_choices(ui0), value="none", label=t(ui0, "fb_engine"),
                                          info=t(ui0, "fb_engine_info")),
                              label="fb_engine", info="fb_engine_info", choices=fallback_choices)
                fb_model = L(gr.Textbox(label=t(ui0, "fb_model"), placeholder=t(ui0, "fb_model_ph")),
                             label="fb_model", placeholder="fb_model_ph")
                L(gr.Markdown(t(ui0, "privacy")), value="privacy")
            with L(gr.Accordion(t(ui0, "acc_display"), open=False), label="acc_display"):
                font = L(gr.Slider(12, 28, value=16, step=1, label=t(ui0, "font")), label="font")
                numbers = L(gr.Checkbox(True, label=t(ui0, "numbers")), label="numbers")
                dict_dd = L(gr.Dropdown(dict_choices(ui0), value=DICT_INTL, label=t(ui0, "dict"),
                                        info=t(ui0, "dict_info")),
                            label="dict", info="dict_info", choices=dict_choices)
            with L(gr.Accordion(t(ui0, "acc_export"), open=True), label="acc_export"):
                files = L(gr.File(label=t(ui0, "files"), file_count="multiple"), label="files")

        # ---- 오른쪽: 줄 수정 (뷰어의 줄 번호를 누르면 열림)
        with L(gr.Sidebar(label=t(ui0, "edit"), open=False, position="right", width=380), label="edit") as edit_bar:
            L(gr.Markdown(t(ui0, "edit_help")), value="edit_help")
            with gr.Row():
                line_no = L(gr.Number(label=t(ui0, "line_no"), precision=0, minimum=1, scale=2, elem_id="jk-line-no"),
                            label="line_no")
                load_btn = L(gr.Button(t(ui0, "load_line"), scale=1, elem_id="jk-load-line"), value="load_line")
            edit_info = gr.Markdown()
            chunk_box = L(gr.Textbox(label=t(ui0, "chunks"), lines=5), label="chunks")
            tr_box = L(gr.Textbox(label=t(ui0, "line_tr")), label="line_tr")
            sent_box = L(gr.Textbox(label=t(ui0, "sent_tr"), visible=False), label="sent_tr")
            with gr.Row():
                retrans_btn = L(gr.Button(t(ui0, "retrans")), value="retrans")
                save_btn = L(gr.Button(t(ui0, "save"), variant="primary"), value="save")
            retry_btn = L(gr.Button(t(ui0, "retry_all")), value="retry_all")

        # ---- 가운데: 입력(번역하면 접힘) + 뷰어
        with gr.Column(elem_id="jk-main"):
            with gr.Row(elem_id="jk-header"):
                L(gr.Markdown(_head_md(ui0), elem_id="jk-head"), value=_head_md)
                ui = gr.Radio(UI_LANGS, value=ui0, show_label=False, container=False)

            with L(gr.Accordion(t(ui0, "input"), open=True), label="input") as input_acc:
                lyrics = L(gr.Textbox(show_label=False, lines=8, max_lines=20, placeholder=t(ui0, "lyrics_ph")),
                           placeholder="lyrics_ph")
                with gr.Row(equal_height=True):
                    title = L(gr.Textbox(show_label=False, placeholder=t(ui0, "title_ph"), scale=3, container=False),
                              placeholder="title_ph")
                    lang = L(gr.Dropdown(source_choices(ui0), value="auto", show_label=False, scale=1,
                                         container=False), choices=source_choices)
                    target = L(gr.Dropdown(target_choices(ui0), value="ko", show_label=False, scale=1,
                                           container=False), choices=target_choices)
                    btn = L(gr.Button(t(ui0, "translate"), variant="primary", scale=1, elem_id="jk-translate"),
                            value="translate")
                    stop = L(gr.Button(t(ui0, "stop"), variant="stop", scale=0, min_width=70), value="stop")
                with gr.Row(elem_id="jk-input-opts"):
                    auto_clean = L(gr.Checkbox(True, label=t(ui0, "auto_clean"), container=False), label="auto_clean")
                    force = L(gr.Checkbox(False, label=t(ui0, "force"), container=False), label="force")
                    clean_btn = L(gr.Button(t(ui0, "clean_only"), size="sm", scale=0), value="clean_only")
                    upload = L(gr.UploadButton(t(ui0, "upload"), file_types=[".txt", ".lrc"], size="sm", scale=0),
                               label="upload")

            with gr.Accordion(t(ui0, "history_count", n=0), open=True, elem_id="jk-history") as hist_acc:
                hist_help = gr.Markdown(t(ui0, "history_help", path=history_dir_label()))
                relabels.append((hist_help, lambda ui, eng: gr.update(value=t(ui, "history_help",
                                                                              path=history_dir_label()))))
                hist_empty = L(gr.Markdown(t(ui0, "history_empty"), visible=False), value="history_empty")
                hist_df = gr.Dataframe(interactive=False, wrap=True, max_height=320, show_search="search",
                                       elem_id="jk-history-table")
                hist_del = L(gr.Button(t(ui0, "hist_delete_current"), size="sm", variant="stop", scale=0),
                             value="hist_delete_current")
            hist_ids = gr.State([])
            hist_sel = gr.State(None)

            with gr.Row(elem_id="jk-toolbar"):
                mode = L(gr.Radio(mode_choices(ui0), value=MODE_SOURCE, show_label=False, container=False),
                         choices=mode_choices)
                unit = L(gr.Radio(unit_choices(ui0), value=UNIT_LINE, show_label=False, container=False,
                                  visible=False), choices=unit_choices)
                reading = L(gr.Checkbox(True, label=t(ui0, "reading"), container=False), label="reading")
                hide = L(gr.Checkbox(False, label=t(ui0, "hide"), container=False), label="hide")
                edit_toggle = L(gr.Button(t(ui0, "edit_toggle"), size="sm", scale=0), value="edit_toggle")
            status = gr.Markdown(elem_id="jk-status")
            output = gr.HTML(to_html(None, MODE_SOURCE), elem_id="jk-viewer")

        E = [engine, model, api_key, base_url, batch, retries]
        V = [mode, unit, font, numbers, hide, reading, dict_dd, ui]
        edit_outputs = [edit_info, chunk_box, tr_box, sent_box]
        tr_inputs = [lyrics, title, lang, target, auto_clean, *E, fb_engine, fb_model, force, *V]
        tr_outputs = [lyrics, output, status, doc_state, files]
        H = [hist_df, hist_ids, hist_acc, hist_empty]

        # UI 언어 — 모든 라벨을 다시 그리고 뷰어도 다시 렌더링
        ui.change(lambda u, eng: [f(u, eng) for _, f in relabels], [ui, engine], [c for c, _ in relabels])

        # 입력
        clean_btn.click(clean_text, [lyrics, lang, target, ui], [lyrics, status])
        upload.upload(load_file, [upload, lang, target, ui], [lyrics, title, status])

        # 번역 — 먼저 입력·히스토리 칸을 접어 뷰어를 넓힌다 (따로 걸면 번역이 끝난 뒤에야 접힌다)
        tr_evt = btn.click(collapse_input, [lyrics, title, ui], [input_acc, hist_acc]) \
            .then(run_translate, tr_inputs, tr_outputs)
        tr_evt.then(history_view, ui, H)
        retry_evt = retry_btn.click(retry_all, [doc_state, *E, *V], [output, status, doc_state, files])
        retry_evt.then(history_view, ui, H)
        stop.click(lambda u: t(u, "stopped"), ui, status, cancels=[tr_evt, retry_evt])

        # 보기 — 직역 단위는 직역이 보일 때만
        gr.on([mode.change, unit.change, font.release, numbers.change, hide.change, reading.change, dict_dd.change,
               ui.change], rerender, [doc_state, *V], [output, files])
        mode.change(lambda m: gr.update(visible=m != MODE_SOURCE), mode, unit)

        # 줄 수정
        load_btn.click(open_editor, [doc_state, line_no, ui], [*edit_outputs, edit_bar])
        line_no.submit(_edit_fields, [doc_state, line_no, ui], edit_outputs)
        edit_toggle.click(lambda: gr.update(open=True), None, edit_bar)
        retrans_btn.click(retranslate_line, [doc_state, line_no, *E, *V],
                          [output, status, doc_state, files, *edit_outputs]).then(history_view, ui, H)
        save_btn.click(save_line, [doc_state, line_no, chunk_box, tr_box, sent_box, engine, model, batch, *V],
                       [output, doc_state, files]).then(history_view, ui, H)

        # 엔진
        engine.input(on_engine_change, [engine, ui], [model, api_key, base_url])
        check_btn.click(check_engine, [engine, model, api_key, base_url, ui], [check_msg, model])
        clear_btn.click(clear_cache, ui)

        # 최근 번역 — 줄을 누르면 저장된 결과를 그대로 연다(번역하지 않음)
        hist_df.select(open_history, [hist_ids, ui, *V[:-1]],
                       [output, status, doc_state, files, hist_sel, lyrics, title, lang, target, input_acc, hist_acc])
        hist_del.click(delete_history, [hist_sel, ui], hist_sel).then(history_view, ui, H)
        ui.change(history_view, ui, H)

        # 설정 기억 (브라우저 저장소)
        remembered = [ui, target, engine, model, base_url, batch, retries, mode, unit, font, numbers, hide, reading,
                      dict_dd, fb_engine, fb_model, auto_clean]
        demo.load(restore_settings, settings,
                  [ui, target, engine, model, api_key, base_url, batch, retries, mode, unit, font, numbers, hide,
                   reading, dict_dd, fb_engine, fb_model, auto_clean]).then(history_view, ui, H)
        gr.on([c.change for c in remembered], save_settings, remembered, settings)

        demo.load(None, js=APP_JS)
    return demo


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    _load_dotenv()
    build_ui().launch(server_name=os.environ.get("HOST", "127.0.0.1"), css=APP_CSS)
