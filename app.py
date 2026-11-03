"""가사 직독직해 번역 툴 — Gradio 웹 UI.

실행: python app.py  →  http://127.0.0.1:7860
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import gradio as gr

from lyrics_tool.backends import BACKENDS, BackendError, OllamaBackend, make_backend
from lyrics_tool.cache import Cache
from lyrics_tool.core import (
    LANG_NAMES, Doc, Translator, apply_edit, chunks_to_text, sentence_of, text_to_chunks,
)
from lyrics_tool.render import MODE_SOURCE, MODES, UNIT_LINE, UNITS, to_html, to_markdown

LANG_CHOICES = [("자동 감지", "auto")] + [(v, k) for k, v in LANG_NAMES.items()]

ENGINE_HINTS = {
    "ollama": ("모델 (예: qwen3:8b, gemma3:12b)", "Ollama 주소 (기본 http://localhost:11434)", False),
    "gemini": ("모델 (예: gemini-2.5-flash)", "", True),
    "openai": ("모델 (예: llama-3.3-70b-versatile)", "Base URL (예: https://api.groq.com/openai/v1)", True),
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


# ---------------------------------------------------------------- 공통 출력


def _status(doc: Doc, t: Translator, note: str = "") -> str:
    done, total = doc.progress()
    lines = doc.lines()
    n = sum(1 for r in lines if not r.blank)
    failed = sum(1 for r in lines if r.error)
    parts = [f"**{LANG_NAMES.get(doc.lang, doc.lang)}**", f"{n}줄", f"구간 {done}/{total}",
             f"엔진 {t.backend.name} `{t.backend.model}`"]
    if failed:
        parts.append(f"⚠ {failed}줄 실패 — 아래 '줄 수정'에서 다시 번역할 수 있습니다")
    return " · ".join(parts) + (f"\n\n{note}" if note else "")


def _export(doc: Doc | None, mode: str, unit: str) -> list[str] | None:
    if doc is None:
        return None
    out_dir = Path(tempfile.gettempdir()) / "lyrics-jikdok"
    out_dir.mkdir(exist_ok=True)
    tag = "원문어순" if mode == MODE_SOURCE else f"한국어어순_{unit.replace(' ', '')}"
    md = out_dir / f"직독직해_{tag}.md"
    js = out_dir / "직독직해_원본.json"
    md.write_text(to_markdown(doc, mode, unit), encoding="utf-8")
    js.write_text(doc.to_json(), encoding="utf-8")
    return [str(md), str(js)]


# ---------------------------------------------------------------- 번역 (점진 표시)


def run_translate(lyrics, lang, engine, model, api_key, base_url, batch, mode, unit, force):
    if not lyrics or not lyrics.strip():
        raise gr.Error("가사를 입력해 주세요.")
    t = make_translator(engine, model, api_key, base_url, batch)
    doc = t.prepare(lyrics, lang, use_cache=not force)
    cached, _ = doc.progress()
    note = f"캐시에서 {cached}개 구간을 불러왔습니다." if cached else ""
    yield to_html(doc, mode, unit), _status(doc, t, note or "번역 중…"), doc, None
    try:
        for doc in t.run(doc):
            yield to_html(doc, mode, unit), _status(doc, t, "번역 중…"), doc, None
    except BackendError as e:
        yield to_html(doc, mode, unit), _status(doc, t, f"⚠ {e}"), doc, _export(doc, mode, unit)
        return
    yield to_html(doc, mode, unit), _status(doc, t, note), doc, _export(doc, mode, unit)


def rerender(mode, unit, doc):
    return to_html(doc, mode, unit), _export(doc, mode, unit)


# ---------------------------------------------------------------- 줄 수정


def _edit_fields(doc: Doc | None, line_no):
    """(안내, 청크, 줄 직역, 문장 직역 update)"""
    empty = ("", "", "", gr.update(visible=False, value=""))
    if doc is None or not line_no:
        return ("먼저 번역을 실행하세요.",) + empty[1:]
    line_no = int(line_no)
    try:
        doc.locate(line_no)
    except KeyError as e:
        return (f"⚠ {e.args[0]}",) + empty[1:]
    r = doc.lines()[line_no - 1]
    if r.pending:
        return (f"**{line_no}줄** `{r.source}` — 아직 번역되지 않았습니다.",) + empty[1:]
    s = sentence_of(doc, line_no)
    info = f"**{line_no}줄** `{r.source}`"
    if r.error:
        info += f"\n\n⚠ {r.error}"
    sent = gr.update(visible=False, value="")
    if s.end > s.start:
        info += f"\n\n{s.start}~{s.end}줄이 한 문장으로 묶여 있습니다. 다시 번역하면 문장 전체를 함께 번역합니다."
        sent = gr.update(visible=True, value=s.ko, label=f"문장 직역 ({s.start}~{s.end}줄)")
    return info, chunks_to_text(r.chunks), r.ko, sent


def load_line(doc, line_no):
    return _edit_fields(doc, line_no)


def retranslate_line(doc, line_no, engine, model, api_key, base_url, batch, mode, unit):
    if doc is None or not line_no:
        raise gr.Error("먼저 번역을 실행하고 줄 번호를 입력하세요.")
    t = make_translator(engine, model, api_key, base_url, batch)
    try:
        t.retranslate(doc, int(line_no))
    except KeyError as e:
        raise gr.Error(e.args[0]) from e
    except BackendError as e:
        raise gr.Error(str(e)) from e
    return (to_html(doc, mode, unit), _status(doc, t, f"{int(line_no)}줄을 다시 번역했습니다."), doc,
            _export(doc, mode, unit), *_edit_fields(doc, line_no))


def save_line(doc, line_no, chunk_text, ko, sent_ko, mode, unit):
    if doc is None or not line_no:
        raise gr.Error("먼저 번역을 실행하고 줄 번호를 입력하세요.")
    try:
        apply_edit(doc, int(line_no), text_to_chunks(chunk_text), ko, sent_ko, cache=get_cache())
    except (KeyError, ValueError) as e:
        raise gr.Error(str(e.args[0])) from e
    gr.Info(f"{int(line_no)}줄 수정 내용을 저장했습니다.")
    return to_html(doc, mode, unit), doc, _export(doc, mode, unit)


def retry_all(doc, engine, model, api_key, base_url, batch, mode, unit):
    if doc is None:
        raise gr.Error("먼저 번역을 실행하세요.")
    t = make_translator(engine, model, api_key, base_url, batch)
    try:
        for doc in t.retry_failed(doc):
            yield to_html(doc, mode, unit), _status(doc, t, "실패한 줄 재시도 중…"), doc, None
    except BackendError as e:
        yield to_html(doc, mode, unit), _status(doc, t, f"⚠ {e}"), doc, _export(doc, mode, unit)
        return
    yield to_html(doc, mode, unit), _status(doc, t, "재시도를 마쳤습니다."), doc, _export(doc, mode, unit)


# ---------------------------------------------------------------- 설정


def on_engine_change(engine):
    model_ph, url_ph, needs_key = ENGINE_HINTS[engine]
    models = OllamaBackend(model="").list_models() if engine == "ollama" else []
    model_ph = model_ph + (f" · 설치됨: {', '.join(models[:5])}" if models else "")
    return (
        gr.update(placeholder=model_ph, value=""),
        gr.update(visible=needs_key, value=""),
        gr.update(visible=bool(url_ph), placeholder=url_ph, value=""),
    )


def clear_cache():
    n = get_cache().clear()
    gr.Info(f"캐시 {n}개 구간을 지웠습니다.")


# ---------------------------------------------------------------- 화면


def build_ui() -> gr.Blocks:
    default_engine = os.environ.get("LYRICS_BACKEND", "ollama")
    if default_engine not in BACKENDS:
        default_engine = "ollama"
    model_ph, url_ph, needs_key = ENGINE_HINTS[default_engine]

    with gr.Blocks(title="가사 직독직해") as demo:
        gr.Markdown("## 🎧 가사 직독직해 번역\n일본어·중국어·영어 가사를 의미 단위로 끊어 한국어로 직역합니다.")
        doc_state = gr.State(None)

        with gr.Row():
            with gr.Column(scale=4):
                lyrics = gr.Textbox(label="가사", lines=18,
                                    placeholder="가사를 붙여넣으세요. 빈 줄은 연 구분으로 유지되며, 연 단위로 나눠 번역합니다.")
                with gr.Row():
                    lang = gr.Dropdown(LANG_CHOICES, value="auto", label="원문 언어", scale=2)
                    btn = gr.Button("번역", variant="primary", scale=1)
                    stop = gr.Button("중단", variant="stop", scale=1)
                force = gr.Checkbox(False, label="캐시 무시하고 새로 번역")
                with gr.Accordion("엔진 설정", open=False):
                    engine = gr.Radio([(v, k) for k, v in BACKENDS.items()], value=default_engine, label="번역 엔진")
                    model = gr.Textbox(label="모델", placeholder=model_ph)
                    api_key = gr.Textbox(label="API 키 (비우면 .env 값 사용)", type="password", visible=needs_key)
                    base_url = gr.Textbox(label="서버 주소", placeholder=url_ph, visible=bool(url_ph))
                    batch = gr.Slider(1, 20, value=8, step=1, label="한 번에 보낼 최대 줄 수",
                                      info="연이 이보다 길면 나눠 보냅니다. 작을수록 거부가 줄고, 클수록 빠릅니다. "
                                           "값을 바꾸면 기존 캐시와 구간이 달라집니다.")
                    gr.Markdown("Ollama는 가사가 PC 밖으로 나가지 않습니다. API 엔진은 입력이 해당 서비스로 전송됩니다.")
                    clear_btn = gr.Button("캐시 비우기", size="sm")

            with gr.Column(scale=6):
                with gr.Row():
                    mode = gr.Radio(MODES, value=MODE_SOURCE, label="보기 방식")
                    unit = gr.Radio(UNITS, value=UNIT_LINE, label="직역 단위 (한국어 어순 보기)")
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
                files = gr.File(label="내보내기 (Markdown · JSON)", file_count="multiple")

        engine_inputs = [engine, model, api_key, base_url, batch]
        view = [mode, unit]
        edit_outputs = [edit_info, chunk_box, ko_box, sent_box]

        engine.change(on_engine_change, engine, [model, api_key, base_url])
        tr_evt = btn.click(run_translate, [lyrics, lang, *engine_inputs, *view, force],
                           [output, status, doc_state, files])
        retry_evt = retry_btn.click(retry_all, [doc_state, *engine_inputs, *view],
                                    [output, status, doc_state, files])
        stop.click(lambda: "⏹ 중단했습니다. 번역된 부분까지는 유지됩니다.", None, status,
                   cancels=[tr_evt, retry_evt])
        mode.change(rerender, [*view, doc_state], [output, files])
        unit.change(rerender, [*view, doc_state], [output, files])

        load_btn.click(load_line, [doc_state, line_no], edit_outputs)
        line_no.submit(load_line, [doc_state, line_no], edit_outputs)
        retrans_btn.click(retranslate_line, [doc_state, line_no, *engine_inputs, *view],
                          [output, status, doc_state, files, *edit_outputs])
        save_btn.click(save_line, [doc_state, line_no, chunk_box, ko_box, sent_box, *view],
                       [output, doc_state, files])
        clear_btn.click(clear_cache)

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
