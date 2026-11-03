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

from lyrics_tool.backends import BACKENDS, BackendError, OllamaBackend, make_backend
from lyrics_tool.cache import Cache, default_title
from lyrics_tool.cleanup import clean_lyrics, read_lyrics_file
from lyrics_tool.core import (
    LANG_NAMES, Doc, Translator, apply_edit, chunks_to_text, sentence_of, text_to_chunks,
)
from lyrics_tool.render import (
    MODE_SOURCE, MODES, UNIT_LINE, UNITS, ViewOptions, to_html, to_markdown, to_print_html,
)

LANG_CHOICES = [("자동 감지", "auto")] + [(v, k) for k, v in LANG_NAMES.items()]
FALLBACK_CHOICES = [("사용 안 함", "none")] + [(v, k) for k, v in BACKENDS.items()]

ENGINE_HINTS = {
    "ollama": ("비우면 OLLAMA_MODEL (기본 qwen3:8b)", "Ollama 주소 (기본 http://localhost:11434)", False),
    "gemini": ("비우면 GEMINI_MODEL (기본 gemini-2.5-flash)", "", True),
    "openai": ("비우면 OPENAI_MODEL", "Base URL (예: https://api.groq.com/openai/v1)", True),
}

DEFAULT_SETTINGS = {
    "engine": "ollama", "model": "", "base_url": "", "batch": 8,
    "mode": MODE_SOURCE, "unit": UNIT_LINE, "font": 16, "numbers": True, "hide": False,
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


def make_translator(engine, model, api_key, base_url, batch) -> Translator:
    backend = make_backend(engine, (model or "").strip(), (api_key or "").strip(), (base_url or "").strip())
    return Translator(backend, batch_size=int(batch), cache=get_cache())


def make_fallback(fb_engine, fb_model, engine, api_key, base_url, batch) -> Translator | None:
    """보조 엔진. 주 엔진과 종류가 같으면 화면의 키·주소를, 다르면 .env 값을 쓴다."""
    if not fb_engine or fb_engine == "none":
        return None
    same = fb_engine == engine
    return make_translator(fb_engine, fb_model, api_key if same else "", base_url if same else "", batch)


def _view(mode, unit, font, numbers, hide):
    return mode, unit, ViewOptions(font_size=int(font), show_numbers=bool(numbers), hide_korean=bool(hide))


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
    md.write_text(to_markdown(doc, mode, unit), encoding="utf-8")
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


def run_translate(lyrics, title, lang, auto_clean, engine, model, api_key, base_url, batch,
                  fb_engine, fb_model, force, mode, unit, font, numbers, hide):
    if not lyrics or not lyrics.strip():
        raise gr.Error("가사를 입력해 주세요.")
    mode, unit, opts = _view(mode, unit, font, numbers, hide)
    notes = []
    if auto_clean:
        lyrics, report = clean_lyrics(lyrics)
        if report:
            notes.append("가사 정리: " + ", ".join(report))

    t = make_translator(engine, model, api_key, base_url, batch)
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

        fb = make_fallback(fb_engine, fb_model, engine, api_key, base_url, batch)
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


def rerender(doc, mode, unit, font, numbers, hide):
    mode, unit, opts = _view(mode, unit, font, numbers, hide)
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


def retranslate_line(doc, line_no, engine, model, api_key, base_url, batch, mode, unit, font, numbers, hide):
    if doc is None or not line_no:
        raise gr.Error("먼저 번역을 실행하고 줄 번호를 입력하세요.")
    mode, unit, opts = _view(mode, unit, font, numbers, hide)
    t = make_translator(engine, model, api_key, base_url, batch)
    try:
        t.retranslate(doc, int(line_no))
    except KeyError as e:
        raise gr.Error(e.args[0]) from e
    except BackendError as e:
        raise gr.Error(str(e)) from e
    return (to_html(doc, mode, unit, opts), _status(doc, t, f"{int(line_no)}줄을 다시 번역했습니다."), doc,
            _export(doc, mode, unit, opts), *_edit_fields(doc, line_no))


def save_line(doc, line_no, chunk_text, ko, sent_ko, mode, unit, font, numbers, hide):
    if doc is None or not line_no:
        raise gr.Error("먼저 번역을 실행하고 줄 번호를 입력하세요.")
    mode, unit, opts = _view(mode, unit, font, numbers, hide)
    try:
        apply_edit(doc, int(line_no), text_to_chunks(chunk_text), ko, sent_ko, cache=get_cache())
    except (KeyError, ValueError) as e:
        raise gr.Error(str(e.args[0])) from e
    gr.Info(f"{int(line_no)}줄 수정 내용을 저장했습니다.")
    return to_html(doc, mode, unit, opts), doc, _export(doc, mode, unit, opts)


def retry_all(doc, engine, model, api_key, base_url, batch, mode, unit, font, numbers, hide):
    if doc is None:
        raise gr.Error("먼저 번역을 실행하세요.")
    mode, unit, opts = _view(mode, unit, font, numbers, hide)
    t = make_translator(engine, model, api_key, base_url, batch)
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
            s["batch"], s["mode"], s["unit"], s["font"], s["numbers"], s["hide"], s["fb_engine"], s["fb_model"],
            s["auto_clean"], gr.update(choices=_history_choices()))


def save_settings(engine, model, base_url, batch, mode, unit, font, numbers, hide, fb_engine, fb_model, auto_clean):
    # API 키는 브라우저에 저장하지 않는다 (.env 사용 권장)
    return dict(engine=engine, model=model or "", base_url=base_url or "", batch=batch, mode=mode, unit=unit,
                font=font, numbers=numbers, hide=hide, fb_engine=fb_engine, fb_model=fb_model or "",
                auto_clean=auto_clean)


# ---------------------------------------------------------------- 화면


def build_ui() -> gr.Blocks:
    default_engine = os.environ.get("LYRICS_BACKEND", "ollama")
    if default_engine not in BACKENDS:
        default_engine = "ollama"
    DEFAULT_SETTINGS["engine"] = default_engine
    model_info, url_ph, needs_key = ENGINE_HINTS[default_engine]

    with gr.Blocks(title="가사 직독직해") as demo:
        gr.Markdown("## 🎧 가사 직독직해 번역\n일본어·중국어·영어 가사를 의미 단위로 끊어 한국어로 직역합니다.")
        doc_state = gr.State(None)
        settings = gr.BrowserState(DEFAULT_SETTINGS, storage_key="lyrics-jikdok-settings")

        with gr.Row():
            with gr.Column(scale=4):
                title = gr.Textbox(label="곡 제목 (선택)", placeholder="비우면 첫 줄로 저장됩니다")
                lyrics = gr.Textbox(label="가사", lines=16,
                                    placeholder="가사를 붙여넣거나 아래에서 .txt/.lrc 파일을 불러오세요. "
                                                "빈 줄은 연 구분으로 유지되며, 연 단위로 나눠 번역합니다.")
                with gr.Row():
                    lang = gr.Dropdown(LANG_CHOICES, value="auto", label="원문 언어", scale=2)
                    btn = gr.Button("번역", variant="primary", scale=1)
                    stop = gr.Button("중단", variant="stop", scale=1)
                with gr.Row():
                    auto_clean = gr.Checkbox(True, label="번역 전 가사 자동 정리")
                    force = gr.Checkbox(False, label="캐시 무시하고 새로 번역")
                with gr.Row():
                    clean_btn = gr.Button("가사 정리만 하기", size="sm")
                    upload = gr.UploadButton("파일 불러오기 (.txt .lrc)", file_types=[".txt", ".lrc"], size="sm")

                with gr.Accordion("엔진 설정", open=False):
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
                    gr.Markdown("**보조 엔진** — 주 엔진에서 실패한 줄만 자동으로 다시 시도합니다. 키·주소는 .env 값을 씁니다.")
                    with gr.Row():
                        fb_engine = gr.Dropdown(FALLBACK_CHOICES, value="none", label="보조 엔진")
                        fb_model = gr.Textbox(label="보조 모델", placeholder="비우면 .env 기본값")
                    gr.Markdown("Ollama는 가사가 PC 밖으로 나가지 않습니다. API 엔진은 입력이 해당 서비스로 전송됩니다.")

                with gr.Accordion("최근 번역", open=False):
                    hist_dd = gr.Dropdown([], label="항목", info="불러오면 저장된 엔진 설정으로 캐시에서 바로 복원합니다.")
                    with gr.Row():
                        hist_load = gr.Button("불러오기", size="sm", variant="primary")
                        hist_refresh = gr.Button("새로고침", size="sm")
                        hist_del = gr.Button("목록에서 삭제", size="sm")

            with gr.Column(scale=6):
                with gr.Row():
                    mode = gr.Radio(MODES, value=MODE_SOURCE, label="보기 방식")
                    unit = gr.Radio(UNITS, value=UNIT_LINE, label="직역 단위")
                with gr.Accordion("표시 옵션", open=False):
                    with gr.Row():
                        font = gr.Slider(12, 28, value=16, step=1, label="글자 크기")
                        numbers = gr.Checkbox(True, label="줄 번호")
                        hide = gr.Checkbox(False, label="한국어 가리기 (누르면 보임)")
                status = gr.Markdown()
                output = gr.HTML(to_html(None, MODE_SOURCE))
                with gr.Accordion("줄 수정", open=False):
                    gr.Markdown("줄 번호를 넣고 불러온 뒤, 현재 엔진 설정으로 다시 번역하거나 직접 고쳐 저장합니다. "
                                "같은 연이 반복되면 함께 반영됩니다.")
                    with gr.Row():
                        line_no = gr.Number(label="줄 번호", precision=0, minimum=1, scale=1)
                        load_btn = gr.Button("불러오기", scale=1)
                    edit_info = gr.Markdown()
                    chunk_box = gr.Textbox(label="청크 (한 줄에 `원문 | 한국어`)", lines=5)
                    ko_box = gr.Textbox(label="줄 직역 (한국어 어순)")
                    sent_box = gr.Textbox(label="문장 직역", visible=False)
                    with gr.Row():
                        retrans_btn = gr.Button("이 줄 다시 번역")
                        save_btn = gr.Button("수정 저장", variant="primary")
                    retry_btn = gr.Button("실패한 줄 모두 다시 번역")
                files = gr.File(label="내보내기 (Markdown · 인쇄용 HTML · JSON)", file_count="multiple")

        E = [engine, model, api_key, base_url, batch]
        V = [mode, unit, font, numbers, hide]
        edit_outputs = [edit_info, chunk_box, ko_box, sent_box]
        tr_inputs = [lyrics, title, lang, auto_clean, *E, fb_engine, fb_model, force, *V]
        tr_outputs = [lyrics, output, status, doc_state, files, hist_dd]

        # 입력
        clean_btn.click(clean_text, lyrics, [lyrics, status])
        upload.upload(load_file, upload, [lyrics, title, status])

        # 번역
        tr_evt = btn.click(run_translate, tr_inputs, tr_outputs)
        retry_evt = retry_btn.click(retry_all, [doc_state, *E, *V], [output, status, doc_state, files])
        stop.click(lambda: "⏹ 중단했습니다. 번역된 부분까지는 유지됩니다.", None, status,
                   cancels=[tr_evt, retry_evt])

        # 보기
        gr.on([mode.change, unit.change, font.release, numbers.change, hide.change],
              rerender, [doc_state, *V], [output, files])

        # 줄 수정
        load_btn.click(_edit_fields, [doc_state, line_no], edit_outputs)
        line_no.submit(_edit_fields, [doc_state, line_no], edit_outputs)
        retrans_btn.click(retranslate_line, [doc_state, line_no, *E, *V],
                          [output, status, doc_state, files, *edit_outputs])
        save_btn.click(save_line, [doc_state, line_no, chunk_box, ko_box, sent_box, *V], [output, doc_state, files])

        # 엔진
        engine.input(on_engine_change, engine, [model, api_key, base_url])
        check_btn.click(check_engine, [engine, model, api_key, base_url], [check_msg, model])
        clear_btn.click(clear_cache)

        # 최근 번역 — 불러온 뒤 바로 번역(캐시 적중으로 즉시 표시)
        hist_load.click(load_history, hist_dd, [lyrics, title, lang, engine, model, api_key, base_url, batch]) \
            .then(run_translate, tr_inputs, tr_outputs)
        hist_refresh.click(refresh_history, None, hist_dd)
        hist_del.click(delete_history, hist_dd, hist_dd)

        # 설정 기억 (브라우저 저장소)
        remembered = [engine, model, base_url, batch, mode, unit, font, numbers, hide, fb_engine, fb_model,
                      auto_clean]
        demo.load(restore_settings, settings,
                  [engine, model, api_key, base_url, batch, mode, unit, font, numbers, hide, fb_engine, fb_model,
                   auto_clean, hist_dd])
        gr.on([c.change for c in remembered], save_settings, remembered, settings)

        # Ctrl/Cmd + Enter 로 번역
        demo.load(None, js="""() => {
            document.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                    const b = [...document.querySelectorAll('button')].find(x => x.innerText.trim() === '번역');
                    if (b) { e.preventDefault(); b.click(); }
                }
            });
        }""")
    return demo


if __name__ == "__main__":
    _load_dotenv()
    build_ui().launch(server_name=os.environ.get("HOST", "127.0.0.1"))
