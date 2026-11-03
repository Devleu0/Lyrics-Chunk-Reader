"""가사 직독직해 번역 툴 — Gradio 웹 UI.

실행: python app.py  →  http://127.0.0.1:7860
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import gradio as gr

from lyrics_tool.backends import BACKENDS, BackendError, OllamaBackend, make_backend
from lyrics_tool.core import LANG_NAMES, LineResult, Translator, results_to_json
from lyrics_tool.render import MODE_SOURCE, MODES, to_html, to_markdown

LANG_CHOICES = [("자동 감지", "auto")] + [(v, k) for k, v in LANG_NAMES.items()]

ENGINE_HINTS = {
    "ollama": ("모델 (예: qwen3:8b, gemma3:12b)", "Ollama 주소 (기본 http://localhost:11434)", False),
    "gemini": ("모델 (예: gemini-2.5-flash)", "", True),
    "openai": ("모델 (예: llama-3.3-70b-versatile)", "Base URL (예: https://api.groq.com/openai/v1)", True),
}


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


def _results_from_state(state: dict | None) -> list[LineResult]:
    return state.get("results", []) if state else []


def run_translate(lyrics, lang, engine, model, api_key, base_url, batch_size, mode,
                  progress=gr.Progress()):
    if not lyrics or not lyrics.strip():
        raise gr.Error("가사를 입력해 주세요.")
    backend = make_backend(engine, model.strip(), api_key.strip(), base_url.strip())
    translator = Translator(backend, batch_size=int(batch_size))

    def on_progress(done: int, total: int, msg: str) -> None:
        progress(done / total if total else 1, desc=msg)

    try:
        results, lang_code = translator.translate(lyrics, lang, on_progress)
    except BackendError as e:
        raise gr.Error(str(e)) from e

    failed = sum(1 for r in results if r.error)
    lines = sum(1 for r in results if not r.blank)
    status = f"**{LANG_NAMES.get(lang_code, lang_code)}** · {lines}줄 · 엔진 {backend.name} `{backend.model}`"
    if failed:
        status += f" · ⚠ {failed}줄 실패 (다른 엔진·모델로 다시 시도해 보세요)"
    state = {"results": results, "lang": lang_code}
    return to_html(results, mode), status, state, _export(state, mode)


def rerender(mode, state):
    results = _results_from_state(state)
    return to_html(results, mode), _export(state, mode) if results else None


def _export(state: dict, mode: str) -> list[str]:
    out_dir = Path(tempfile.gettempdir()) / "lyrics-jikdok"
    out_dir.mkdir(exist_ok=True)
    tag = "원문어순" if mode == MODE_SOURCE else "한국어어순"
    md = out_dir / f"직독직해_{tag}.md"
    js = out_dir / "직독직해_원본.json"
    md.write_text(to_markdown(state["results"], mode), encoding="utf-8")
    js.write_text(results_to_json(state["results"], state["lang"]), encoding="utf-8")
    return [str(md), str(js)]


def on_engine_change(engine):
    model_ph, url_ph, needs_key = ENGINE_HINTS[engine]
    models = OllamaBackend(model="").list_models() if engine == "ollama" else []
    model_ph = model_ph + (f" · 설치됨: {', '.join(models[:5])}" if models else "")
    return (
        gr.update(placeholder=model_ph, value=""),
        gr.update(visible=needs_key, value=""),
        gr.update(visible=bool(url_ph), placeholder=url_ph, value=""),
    )


def build_ui() -> gr.Blocks:
    default_engine = os.environ.get("LYRICS_BACKEND", "ollama")
    if default_engine not in BACKENDS:
        default_engine = "ollama"
    model_ph, url_ph, needs_key = ENGINE_HINTS[default_engine]

    with gr.Blocks(title="가사 직독직해") as demo:
        gr.Markdown("## 🎧 가사 직독직해 번역\n일본어·중국어·영어 가사를 의미 단위로 끊어 한국어로 직역합니다.")
        state = gr.State(None)

        with gr.Row():
            with gr.Column(scale=4):
                lyrics = gr.Textbox(label="가사", lines=18, placeholder="가사를 붙여넣으세요. 빈 줄은 연 구분으로 유지됩니다.")
                with gr.Row():
                    lang = gr.Dropdown(LANG_CHOICES, value="auto", label="원문 언어")
                    btn = gr.Button("번역", variant="primary")
                with gr.Accordion("엔진 설정", open=False):
                    engine = gr.Radio([(v, k) for k, v in BACKENDS.items()], value=default_engine, label="번역 엔진")
                    model = gr.Textbox(label="모델", placeholder=model_ph)
                    api_key = gr.Textbox(label="API 키 (비우면 .env 값 사용)", type="password", visible=needs_key)
                    base_url = gr.Textbox(label="서버 주소", placeholder=url_ph, visible=bool(url_ph))
                    batch = gr.Slider(1, 20, value=8, step=1, label="한 번에 보낼 줄 수",
                                      info="작게 할수록 거부·차단이 줄고, 크게 할수록 빠릅니다.")
                    gr.Markdown("Ollama는 가사가 PC 밖으로 나가지 않습니다. API 엔진은 입력이 해당 서비스로 전송됩니다.")

            with gr.Column(scale=6):
                mode = gr.Radio(MODES, value=MODE_SOURCE, label="보기 방식")
                status = gr.Markdown()
                output = gr.HTML(to_html([], MODE_SOURCE))
                files = gr.File(label="내보내기 (Markdown · JSON)", file_count="multiple")

        engine.change(on_engine_change, engine, [model, api_key, base_url])
        btn.click(run_translate, [lyrics, lang, engine, model, api_key, base_url, batch, mode],
                  [output, status, state, files])
        mode.change(rerender, [mode, state], [output, files])
    return demo


if __name__ == "__main__":
    _load_dotenv()
    build_ui().launch(server_name=os.environ.get("HOST", "127.0.0.1"))
