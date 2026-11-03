"""가사 직독직해 번역 툴 — Gradio 웹 UI.

실행: python app.py  →  http://127.0.0.1:7860
같은 와이파이의 폰에서 쓰려면: HOST=0.0.0.0 python app.py → http://<PC의 IP>:7860
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import gradio as gr

from lyrics_tool.backends import BACKENDS, GEMINI_DEFAULT_MODEL, BackendError, OllamaBackend, make_backend
from lyrics_tool.cache import Cache, default_title
from lyrics_tool.cleanup import clean_lyrics, read_lyrics_file
from lyrics_tool.core import (
    LANG_NAMES, Doc, Translator, apply_edit, chunks_to_text, sentence_of, text_to_chunks,
)
from lyrics_tool.reading import DICT_NAVER, DICTS
from lyrics_tool.render import (
    MODE_SOURCE, MODES, UNIT_LINE, UNITS, ViewOptions, to_html, to_markdown, to_print_html,
)

LANG_CHOICES = [("자동 감지", "auto")] + [(v, k) for k, v in LANG_NAMES.items()]
FALLBACK_CHOICES = [("사용 안 함", "none")] + [(v, k) for k, v in BACKENDS.items()]

ENGINE_HINTS = {
    "ollama": ("비우면 OLLAMA_MODEL (기본 qwen3:8b)", "Ollama 주소 (기본 http://localhost:11434)", False),
    "gemini": (f"비우면 GEMINI_MODEL (기본 {GEMINI_DEFAULT_MODEL}, 빠르게: gemini-3.5-flash-lite)", "", True),
    "openai": ("비우면 OPENAI_MODEL", "Base URL (예: https://api.groq.com/openai/v1)", True),
}

DEFAULT_SETTINGS = {
    "engine": "ollama", "model": "", "base_url": "", "batch": 8, "retries": 3,
    "mode": MODE_SOURCE, "unit": UNIT_LINE, "font": 16, "numbers": True, "hide": False,
    "reading": True, "dict": DICT_NAVER,
    "fb_engine": "none", "fb_model": "", "auto_clean": True,
}

CACHE: Cache | None = None


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
        CACHE = Cache(os.environ.get("LYRICS_CACHE") or Path.home() / ".lyrics-jikdok" / "cache.db")
    return CACHE


def make_translator(engine, model, api_key, base_url, batch, retries=3) -> Translator:
    backend = make_backend(engine, (model or "").strip(), (api_key or "").strip(), (base_url or "").strip(),
                           int(retries))
    return Translator(backend, batch_size=int(batch), cache=get_cache())


def make_fallback(fb_engine, fb_model, engine, api_key, base_url, batch, retries=3) -> Translator | None:
    """보조 엔진. 주 엔진과 종류가 같으면 화면의 키·주소를, 다르면 .env 값을 쓴다."""
    if not fb_engine or fb_engine == "none":
        return None
    same = fb_engine == engine
    return make_translator(fb_engine, fb_model, api_key if same else "", base_url if same else "", batch, retries)


def _view(mode, unit, font, numbers, hide, reading, dictionary):
    return mode, unit, ViewOptions(font_size=int(font), show_numbers=bool(numbers), hide_korean=bool(hide),
                                   reading=bool(reading), dictionary=dictionary or DICT_NAVER)


# ---------------------------------------------------------------- 공통 출력


def _status(doc: Doc, t: Translator, note: str = "") -> str:
    done, total = doc.progress()
    lines = doc.lines()
    n = sum(1 for r in lines if not r.blank)
    failed = sum(1 for r in lines if r.error)
    parts = [f"**{doc.title}**" if doc.title else "", f"{LANG_NAMES.get(doc.lang, doc.lang)}", f"{n}줄",
             f"구간 {done}/{total}", f"엔진 {t.backend.name} `{t.backend.model}`"]
    if failed:
        parts.append(f"⚠ {failed}줄 실패 — '줄 수정'에서 다시 번역할 수 있습니다")
    return " · ".join(p for p in parts if p) + (f"\n\n{note}" if note else "")


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_")[:40] or "lyrics"


def _export(doc: Doc | None, mode, unit, opts: ViewOptions) -> list[str] | None:
    if doc is None:
        return None
    out_dir = Path(tempfile.gettempdir()) / "lyrics-jikdok"
    out_dir.mkdir(exist_ok=True)
    base = _safe(doc.title)
    tag = "원문어순" if mode == MODE_SOURCE else f"{mode.split(' ')[0]}_{unit.replace(' ', '')}"
    md = out_dir / f"{base}_{tag}.md"
    html = out_dir / f"{base}_{tag}_인쇄용.html"
    js = out_dir / f"{base}_원본.json"
    md.write_text(to_markdown(doc, mode, unit, opts), encoding="utf-8")
    meta = f"{LANG_NAMES.get(doc.lang, doc.lang)} · {mode} · {unit}"
    html.write_text(to_print_html(doc, mode, unit, opts, doc.title or "가사 직독직해", meta), encoding="utf-8")
    js.write_text(doc.to_json(), encoding="utf-8")
    return [str(md), str(html), str(js)]


def _history_choices():
    return [(h.label, h.id) for h in get_cache().list_history()]


# ---------------------------------------------------------------- 입력 정리


def clean_text(lyrics):
    text, report = clean_lyrics(lyrics or "")
    msg = "정리할 내용이 없습니다." if not report else "가사 정리: " + ", ".join(report)
    return text, msg


def load_file(path):
    if not path:
        return gr.update(), gr.update(), ""
    text, report = clean_lyrics(read_lyrics_file(path))
    msg = f"파일을 불러왔습니다: {Path(path).name}"
    if report:
        msg += "\n\n가사 정리: " + ", ".join(report)
    return text, Path(path).stem, msg


# ---------------------------------------------------------------- 번역 (점진 표시)


def run_translate(lyrics, title, lang, auto_clean, engine, model, api_key, base_url, batch, retries,
                  fb_engine, fb_model, force, *view):
    if not lyrics or not lyrics.strip():
        raise gr.Error("가사를 입력해 주세요.")
    mode, unit, opts = _view(*view)
    notes = []
    if auto_clean:
        lyrics, report = clean_lyrics(lyrics)
        if report:
            notes.append("가사 정리: " + ", ".join(report))

    t = make_translator(engine, model, api_key, base_url, batch, retries)
    doc = t.prepare(lyrics, lang, use_cache=not force)
    doc.title = (title or "").strip() or default_title(lyrics)
    get_cache().save_history(doc.title, lyrics, doc.lang, engine, t.backend.model, int(batch))
    hist = gr.update(choices=_history_choices())

    cached, _ = doc.progress()
    if cached:
        notes.append(f"캐시에서 {cached}개 구간을 불러왔습니다.")
    note = "\n\n".join(notes)
    yield lyrics, to_html(doc, mode, unit, opts), _status(doc, t, note or "번역 중…"), doc, None, hist

    try:
        for doc in t.run(doc):
            yield gr.update(), to_html(doc, mode, unit, opts), _status(doc, t, "번역 중…"), doc, None, gr.update()

        fb = make_fallback(fb_engine, fb_model, engine, api_key, base_url, batch, retries)
        failed = sum(1 for r in doc.lines() if r.error)
        if fb and failed:
            for doc in fb.retry_failed(doc):
                yield (gr.update(), to_html(doc, mode, unit, opts),
                       _status(doc, t, f"보조 엔진({fb.backend.name} `{fb.backend.model}`)으로 실패한 줄 재시도 중…"),
                       doc, None, gr.update())
            fixed = failed - sum(1 for r in doc.lines() if r.error)
            notes.append(f"보조 엔진으로 {fixed}/{failed}줄을 번역했습니다.")
    except BackendError as e:
        notes.append(f"⚠ {e}")
    yield gr.update(), to_html(doc, mode, unit, opts), _status(doc, t, "\n\n".join(notes)), doc, \
        _export(doc, mode, unit, opts), gr.update()


def rerender(doc, *view):
    mode, unit, opts = _view(*view)
    return to_html(doc, mode, unit, opts), _export(doc, mode, unit, opts)


# ---------------------------------------------------------------- 줄 수정


def _edit_fields(doc: Doc | None, line_no):
    """(안내, 청크, 줄 직역, 문장 직역 update)"""
    empty = ("", "", gr.update(visible=False, value=""))
    if doc is None or not line_no:
        return ("먼저 번역을 실행하세요.",) + empty
    line_no = int(line_no)
    try:
        doc.locate(line_no)
    except KeyError as e:
        return (f"⚠ {e.args[0]}",) + empty
    r = doc.lines()[line_no - 1]
    if r.pending:
        return (f"**{line_no}줄** `{r.source}` — 아직 번역되지 않았습니다.",) + empty
    s = sentence_of(doc, line_no)
    info = f"**{line_no}줄** `{r.source}`"
    if r.error:
        info += f"\n\n⚠ {r.error}"
    sent = gr.update(visible=False, value="")
    if s.end > s.start:
        info += f"\n\n{s.start}~{s.end}줄이 한 문장으로 묶여 있습니다. 다시 번역하면 문장 전체를 함께 번역합니다."
        sent = gr.update(visible=True, value=s.ko, label=f"문장 직역 ({s.start}~{s.end}줄)")
    return info, chunks_to_text(r.chunks), r.ko, sent


def retranslate_line(doc, line_no, engine, model, api_key, base_url, batch, retries, *view):
    if doc is None or not line_no:
        raise gr.Error("먼저 번역을 실행하고 줄 번호를 입력하세요.")
    mode, unit, opts = _view(*view)
    t = make_translator(engine, model, api_key, base_url, batch, retries)
    try:
        t.retranslate(doc, int(line_no))
    except KeyError as e:
        raise gr.Error(e.args[0]) from e
    except BackendError as e:
        raise gr.Error(str(e)) from e
    return (to_html(doc, mode, unit, opts), _status(doc, t, f"{int(line_no)}줄을 다시 번역했습니다."), doc,
            _export(doc, mode, unit, opts), *_edit_fields(doc, line_no))


def save_line(doc, line_no, chunk_text, ko, sent_ko, *view):
    if doc is None or not line_no:
        raise gr.Error("먼저 번역을 실행하고 줄 번호를 입력하세요.")
    mode, unit, opts = _view(*view)
    try:
        apply_edit(doc, int(line_no), text_to_chunks(chunk_text), ko, sent_ko, cache=get_cache())
    except (KeyError, ValueError) as e:
        raise gr.Error(str(e.args[0])) from e
    gr.Info(f"{int(line_no)}줄 수정 내용을 저장했습니다.")
    return to_html(doc, mode, unit, opts), doc, _export(doc, mode, unit, opts)


def retry_all(doc, engine, model, api_key, base_url, batch, retries, *view):
    if doc is None:
        raise gr.Error("먼저 번역을 실행하세요.")
    mode, unit, opts = _view(*view)
    t = make_translator(engine, model, api_key, base_url, batch, retries)
    try:
        for doc in t.retry_failed(doc):
            yield to_html(doc, mode, unit, opts), _status(doc, t, "실패한 줄 재시도 중…"), doc, None
    except BackendError as e:
        yield to_html(doc, mode, unit, opts), _status(doc, t, f"⚠ {e}"), doc, _export(doc, mode, unit, opts)
        return
    yield to_html(doc, mode, unit, opts), _status(doc, t, "재시도를 마쳤습니다."), doc, _export(doc, mode, unit, opts)


# ---------------------------------------------------------------- 엔진 설정


def _engine_visibility(engine):
    _, url_ph, needs_key = ENGINE_HINTS[engine]
    return gr.update(visible=needs_key), gr.update(visible=bool(url_ph), placeholder=url_ph)


def on_engine_change(engine):
    """사용자가 엔진을 바꿨을 때만 호출(input 이벤트) — 저장된 설정 복원과 겹치지 않게."""
    models = OllamaBackend(model="", host=os.environ.get("OLLAMA_HOST", "http://localhost:11434")).list_models() \
        if engine == "ollama" else []
    key_u, url_u = _engine_visibility(engine)
    return (gr.update(choices=models, value="", info=ENGINE_HINTS[engine][0]),
            gr.update(value="", visible=key_u["visible"]),
            gr.update(value="", visible=url_u["visible"], placeholder=url_u["placeholder"]))


def check_engine(engine, model, api_key, base_url):
    backend = make_backend(engine, (model or "").strip(), (api_key or "").strip(), (base_url or "").strip())
    r = backend.check()
    icon = "✅" if r.ok else "⚠"
    more = f"\n\n사용 가능한 모델 {len(r.models)}개를 모델 목록에 넣었습니다." if r.models else ""
    return f"{icon} {r.message}{more}", gr.update(choices=r.models[:200])


def clear_cache():
    n = get_cache().clear()
    gr.Info(f"캐시 {n}개 구간을 지웠습니다.")


# ---------------------------------------------------------------- 최근 번역


def load_history(item_id):
    h = get_cache().get_history(int(item_id)) if item_id else None
    if h is None:
        raise gr.Error("불러올 항목을 고르세요.")
    key_u, url_u = _engine_visibility(h.engine)
    return h.lyrics, h.title, h.lang, h.engine, gr.update(value=h.model, info=ENGINE_HINTS[h.engine][0]), \
        key_u, url_u, h.batch


def delete_history(item_id):
    if item_id:
        get_cache().delete_history(int(item_id))
    return gr.update(choices=_history_choices(), value=None)


def refresh_history():
    return gr.update(choices=_history_choices())


# ---------------------------------------------------------------- 설정 기억


def restore_settings(saved):
    s = {**DEFAULT_SETTINGS, **(saved or {})}
    if s["engine"] not in BACKENDS:
        s["engine"] = DEFAULT_SETTINGS["engine"]
    key_u, url_u = _engine_visibility(s["engine"])
    return (s["engine"], gr.update(value=s["model"], info=ENGINE_HINTS[s["engine"]][0]), key_u,
            gr.update(value=s["base_url"], visible=url_u["visible"], placeholder=url_u["placeholder"]),
            s["batch"], s["retries"], s["mode"], s["unit"], s["font"], s["numbers"], s["hide"], s["reading"],
            s["dict"] if s["dict"] in DICTS else DICT_NAVER, s["fb_engine"], s["fb_model"], s["auto_clean"],
            gr.update(choices=_history_choices()))


def save_settings(engine, model, base_url, batch, retries, mode, unit, font, numbers, hide, reading, dictionary,
                  fb_engine, fb_model, auto_clean):
    # API 키는 브라우저에 저장하지 않는다 (.env 사용 권장)
    return dict(engine=engine, model=model or "", base_url=base_url or "", batch=batch, retries=retries,
                mode=mode, unit=unit, font=font, numbers=numbers, hide=hide, reading=reading, dict=dictionary,
                fb_engine=fb_engine, fb_model=fb_model or "", auto_clean=auto_clean)


# ---------------------------------------------------------------- 화면


INPUT_LABEL = "가사 입력"

APP_CSS = """
.gradio-container { overflow: clip !important; }  /* hidden이면 툴바 sticky가 동작하지 않는다 */
#jk-main { max-width: 1000px; margin: 0 auto; width: 100%; }
#jk-head h2 { margin: 0 0 2px; }
#jk-head p { margin: 0; opacity: .7; font-size: .9em; }
#jk-toolbar { position: sticky; top: 0; z-index: 20; background: var(--body-background-fill);
              padding: 6px 2px; border-bottom: 1px solid var(--border-color-primary);
              gap: 6px 12px; align-items: center; flex-wrap: wrap; }
#jk-toolbar > *, #jk-input-opts > * { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; }
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


def collapse_input(lyrics, title):
    """번역을 시작하면 입력 칸을 접고, 접힌 제목에 곡 이름과 줄 수를 보여 준다."""
    text = (lyrics or "").strip()
    if not text:
        return gr.update(open=True, label=INPUT_LABEL)
    n = sum(1 for line in text.splitlines() if line.strip())
    name = (title or "").strip() or default_title(text)
    return gr.update(open=False, label=f"{INPUT_LABEL} — {name} · {n}줄")


def open_editor(doc, line_no):
    return (*_edit_fields(doc, line_no), gr.update(open=True))


def build_ui() -> gr.Blocks:
    default_engine = os.environ.get("LYRICS_BACKEND", "ollama")
    if default_engine not in BACKENDS:
        default_engine = "ollama"
    DEFAULT_SETTINGS["engine"] = default_engine
    model_info, url_ph, needs_key = ENGINE_HINTS[default_engine]

    with gr.Blocks(title="가사 직독직해") as demo:
        doc_state = gr.State(None)
        settings = gr.BrowserState(DEFAULT_SETTINGS, storage_key="lyrics-jikdok-settings")

        # ---- 왼쪽: 설정 (자주 바꾸지 않는 것)
        with gr.Sidebar(label="설정", open=False, width=340):
            with gr.Accordion("엔진", open=True):
                engine = gr.Radio([(v, k) for k, v in BACKENDS.items()], value=default_engine, label="번역 엔진")
                model = gr.Dropdown([], value="", label="모델", info=model_info, allow_custom_value=True)
                api_key = gr.Textbox(label="API 키 (비우면 .env 값 사용, 저장되지 않음)", type="password",
                                     visible=needs_key)
                base_url = gr.Textbox(label="서버 주소", placeholder=url_ph, visible=bool(url_ph))
                with gr.Row():
                    check_btn = gr.Button("연결 확인", size="sm")
                    clear_btn = gr.Button("캐시 비우기", size="sm")
                check_msg = gr.Markdown()
                batch = gr.Slider(1, 20, value=8, step=1, label="한 번에 보낼 최대 줄 수",
                                  info="연이 이보다 길면 나눠 보냅니다. 작을수록 거부가 줄고, 클수록 빠릅니다. "
                                       "값을 바꾸면 기존 캐시와 구간이 달라집니다.")
                retries = gr.Slider(0, 10, value=3, step=1, label="요청 실패 시 재시도 횟수",
                                    info="연결 끊김·시간 초과·한도 초과(429)·서버 과부하(5xx)일 때 기다렸다가 "
                                         "다시 요청합니다. 서버가 알려 준 대기 시간, 없으면 2·4·8…초.")
                fb_engine = gr.Dropdown(FALLBACK_CHOICES, value="none", label="보조 엔진",
                                        info="주 엔진에서 실패한 줄만 다시 시도합니다. 키·주소는 .env 값을 씁니다.")
                fb_model = gr.Textbox(label="보조 모델", placeholder="비우면 .env 기본값")
                gr.Markdown("Ollama는 가사가 PC 밖으로 나가지 않습니다. API 엔진은 입력이 해당 서비스로 전송됩니다.")
            with gr.Accordion("표시", open=False):
                font = gr.Slider(12, 28, value=16, step=1, label="글자 크기")
                numbers = gr.Checkbox(True, label="줄 번호 (누르면 그 줄 수정)")
                dict_dd = gr.Dropdown(DICTS, value=DICT_NAVER, label="청크 사전 링크",
                                      info="끊어읽기 카드의 원문을 누르면 새 탭에서 사전을 엽니다.")
            with gr.Accordion("최근 번역", open=False):
                hist_dd = gr.Dropdown([], label="항목", info="불러오면 저장된 엔진 설정으로 캐시에서 바로 복원합니다.")
                with gr.Row():
                    hist_load = gr.Button("불러오기", size="sm", variant="primary")
                    hist_refresh = gr.Button("새로고침", size="sm")
                    hist_del = gr.Button("삭제", size="sm")
            with gr.Accordion("내보내기", open=True):
                files = gr.File(label="Markdown · 인쇄용 HTML · JSON", file_count="multiple")

        # ---- 오른쪽: 줄 수정 (뷰어의 줄 번호를 누르면 열림)
        with gr.Sidebar(label="줄 수정", open=False, position="right", width=380) as edit_bar:
            gr.Markdown("뷰어의 **줄 번호**를 누르면 그 줄을 불러옵니다. 현재 엔진으로 다시 번역하거나 직접 고쳐 "
                        "저장하세요. 같은 연이 반복되면 함께 반영됩니다.")
            with gr.Row():
                line_no = gr.Number(label="줄 번호", precision=0, minimum=1, scale=2, elem_id="jk-line-no")
                load_btn = gr.Button("불러오기", scale=1, elem_id="jk-load-line")
            edit_info = gr.Markdown()
            chunk_box = gr.Textbox(label="청크 (한 줄에 `원문 | 한국어`)", lines=5)
            ko_box = gr.Textbox(label="줄 직역 (한국어 어순)")
            sent_box = gr.Textbox(label="문장 직역", visible=False)
            with gr.Row():
                retrans_btn = gr.Button("이 줄 다시 번역")
                save_btn = gr.Button("수정 저장", variant="primary")
            retry_btn = gr.Button("실패한 줄 모두 다시 번역")

        # ---- 가운데: 입력(번역하면 접힘) + 뷰어
        with gr.Column(elem_id="jk-main"):
            gr.Markdown("## 🎧 가사 직독직해\n일본어·중국어·영어 가사를 의미 단위로 끊어 한국어로 직역합니다. "
                        "설정은 왼쪽, 줄 수정은 오른쪽 사이드바에 있습니다.", elem_id="jk-head")

            with gr.Accordion(INPUT_LABEL, open=True) as input_acc:
                lyrics = gr.Textbox(show_label=False, lines=8, max_lines=20,
                                    placeholder="가사를 붙여넣고 번역 (Ctrl/Cmd+Enter). 빈 줄은 연 구분으로 유지됩니다.\n"
                                                "[Chorus]·타임스탬프·크레딧·섞인 한국어 번역 줄은 자동으로 정리합니다.")
                with gr.Row(equal_height=True):
                    title = gr.Textbox(show_label=False, placeholder="곡 제목 (선택, 비우면 첫 줄)", scale=3,
                                       container=False)
                    lang = gr.Dropdown(LANG_CHOICES, value="auto", show_label=False, scale=1, container=False)
                    btn = gr.Button("번역", variant="primary", scale=1, elem_id="jk-translate")
                    stop = gr.Button("중단", variant="stop", scale=0, min_width=70)
                with gr.Row(elem_id="jk-input-opts"):
                    auto_clean = gr.Checkbox(True, label="자동 정리", container=False)
                    force = gr.Checkbox(False, label="캐시 무시", container=False)
                    clean_btn = gr.Button("정리만 하기", size="sm", scale=0)
                    upload = gr.UploadButton("파일 (.txt .lrc)", file_types=[".txt", ".lrc"], size="sm", scale=0)

            with gr.Row(elem_id="jk-toolbar"):
                mode = gr.Radio(MODES, value=MODE_SOURCE, show_label=False, container=False)
                unit = gr.Radio(UNITS, value=UNIT_LINE, show_label=False, container=False, visible=False)
                reading = gr.Checkbox(True, label="발음", container=False)
                hide = gr.Checkbox(False, label="한국어 가리기", container=False)
                edit_toggle = gr.Button("✎ 줄 수정", size="sm", scale=0)
            status = gr.Markdown(elem_id="jk-status")
            output = gr.HTML(to_html(None, MODE_SOURCE), elem_id="jk-viewer")

        E = [engine, model, api_key, base_url, batch, retries]
        V = [mode, unit, font, numbers, hide, reading, dict_dd]
        edit_outputs = [edit_info, chunk_box, ko_box, sent_box]
        tr_inputs = [lyrics, title, lang, auto_clean, *E, fb_engine, fb_model, force, *V]
        tr_outputs = [lyrics, output, status, doc_state, files, hist_dd]

        # 입력
        clean_btn.click(clean_text, lyrics, [lyrics, status])
        upload.upload(load_file, upload, [lyrics, title, status])

        # 번역 — 시작하면 입력 칸을 접어 뷰어를 넓힌다
        tr_evt = btn.click(run_translate, tr_inputs, tr_outputs)
        btn.click(collapse_input, [lyrics, title], input_acc)
        retry_evt = retry_btn.click(retry_all, [doc_state, *E, *V], [output, status, doc_state, files])
        stop.click(lambda: "⏹ 중단했습니다. 번역된 부분까지는 유지됩니다.", None, status,
                   cancels=[tr_evt, retry_evt])

        # 보기 — 직역 단위는 한국어 직역이 보일 때만
        gr.on([mode.change, unit.change, font.release, numbers.change, hide.change, reading.change, dict_dd.change],
              rerender, [doc_state, *V], [output, files])
        mode.change(lambda m: gr.update(visible=m != MODE_SOURCE), mode, unit)

        # 줄 수정
        load_btn.click(open_editor, [doc_state, line_no], [*edit_outputs, edit_bar])
        line_no.submit(_edit_fields, [doc_state, line_no], edit_outputs)
        edit_toggle.click(lambda: gr.update(open=True), None, edit_bar)
        retrans_btn.click(retranslate_line, [doc_state, line_no, *E, *V],
                          [output, status, doc_state, files, *edit_outputs])
        save_btn.click(save_line, [doc_state, line_no, chunk_box, ko_box, sent_box, *V], [output, doc_state, files])

        # 엔진
        engine.input(on_engine_change, engine, [model, api_key, base_url])
        check_btn.click(check_engine, [engine, model, api_key, base_url], [check_msg, model])
        clear_btn.click(clear_cache)

        # 최근 번역 — 불러온 뒤 바로 번역(캐시 적중으로 즉시 표시)
        hist_load.click(load_history, hist_dd, [lyrics, title, lang, engine, model, api_key, base_url, batch]) \
            .then(collapse_input, [lyrics, title], input_acc) \
            .then(run_translate, tr_inputs, tr_outputs)
        hist_refresh.click(refresh_history, None, hist_dd)
        hist_del.click(delete_history, hist_dd, hist_dd)

        # 설정 기억 (브라우저 저장소)
        remembered = [engine, model, base_url, batch, retries, *V, fb_engine, fb_model, auto_clean]
        demo.load(restore_settings, settings,
                  [engine, model, api_key, base_url, batch, retries, *V, fb_engine, fb_model, auto_clean, hist_dd])
        gr.on([c.change for c in remembered], save_settings, remembered, settings)

        demo.load(None, js=APP_JS)
    return demo


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    _load_dotenv()
    build_ui().launch(server_name=os.environ.get("HOST", "127.0.0.1"), css=APP_CSS)
