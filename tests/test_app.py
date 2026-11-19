"""app.py의 이벤트 처리 함수 — 가짜 엔진과 임시 히스토리·캐시로 화면 없이 부른다."""

import types

import gradio as gr
import pytest

import app
from lyrics_tool.backends import BackendError
from lyrics_tool.cache import Cache
from lyrics_tool.export import FMT_ANKI, FMT_MD, FMT_MOBILE
from lyrics_tool.history import History

from test_core import FakeBackend

VIEW = ["source", "line", 16, True, False, True, "intl", "ko"]  # app.py의 V 순서
ENGINE = ["ollama", "fake", "", "", 8, 0]  # engine, model, api_key, base_url, batch, retries


@pytest.fixture
def env(tmp_path, monkeypatch):
    """가짜 엔진 하나를 모든 번역기가 같이 쓴다. backend.calls로 엔진 호출을 센다."""
    backend = FakeBackend()
    monkeypatch.setattr(app, "make_backend", lambda *a, **k: backend)
    monkeypatch.setattr(app, "HISTORY", History(tmp_path / "history"))
    monkeypatch.setattr(app, "CACHE", Cache(":memory:"))
    monkeypatch.setattr(app, "EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setattr(gr, "Info", lambda *a, **k: None)
    return types.SimpleNamespace(backend=backend, history=app.HISTORY, tmp=tmp_path)


def _translate(lyrics, title="T", force=False, target="ko"):
    gen = app.run_translate(lyrics, title, "en", target, True, *ENGINE, "none", "", force, *VIEW)
    return list(gen)


def test_run_translate_streams_and_saves(env):
    steps = _translate("hello world\nsee you\n\nagain")
    lyrics, html, status, doc, files = steps[-1]
    assert len(steps) >= 3  # 시작 + 구간마다 + 끝
    assert doc.complete and doc.title == "T"
    assert 'class="jk-chunk"' in html and "hello" in html
    assert files and any(f.endswith("_mobile.html") for f in files)
    assert [e.title for e in env.history.list()] == ["T"]


def test_run_translate_uses_cache_second_time(env):
    _translate("hello world")
    n = len(env.backend.calls)
    _translate("hello world")
    assert len(env.backend.calls) == n  # 캐시에서 불러와 엔진을 다시 부르지 않는다
    _translate("hello world", force=True)
    assert len(env.backend.calls) > n


def test_run_translate_rejects_empty_and_same_language(env):
    with pytest.raises(gr.Error):
        _translate("   ")
    with pytest.raises(gr.Error):
        _translate("hello", target="en")


def test_run_translate_reports_backend_error(env):
    env.backend.raise_backend = True
    *_, (_, _, status, doc, _) = _translate("hello")
    assert "⚠" in status and not doc.complete
    assert env.history.list() == []  # 미완성은 저장하지 않는다


def test_edit_line_and_save(env):
    *_, (_, _, _, doc, _) = _translate("hello world")
    info, chunks, tr, _ = app._edit_fields(doc, 1, "ko")
    assert "hello | <hello>" in chunks and tr == "KO hello world"
    html, doc2, _ = app.save_line(doc, 1, "hello | 안녕\nworld | 세상", "안녕 세상", None, "ollama", "fake", 8, *VIEW)
    assert doc2.lines()[0].tr == "안녕 세상" and "안녕" in html
    saved, _ = env.history.load(env.history.list()[0].id)
    assert saved.lines()[0].tr == "안녕 세상"


def test_save_line_errors(env):
    *_, (_, _, _, doc, _) = _translate("hello")
    with pytest.raises(gr.Error):
        app.save_line(None, 1, "", "", None, "ollama", "", 8, *VIEW)
    with pytest.raises(gr.Error):
        app.save_line(doc, 1, "", "x", None, "ollama", "", 8, *VIEW)  # 청크 없음
    with pytest.raises(gr.Error):
        app.save_line(doc, 9, "a | b", "x", None, "ollama", "", 8, *VIEW)  # 없는 줄


def test_retranslate_line(env):
    *_, (_, _, _, doc, _) = _translate("hello world\nbye")
    env.backend.tag = "NEW"
    out = app.retranslate_line(doc, 2, *ENGINE, *VIEW)
    doc = out[2]
    assert doc.lines()[1].tr == "NEW bye" and doc.lines()[0].tr == "KO hello world"


def test_retranslate_line_backend_error(env):
    *_, (_, _, _, doc, _) = _translate("hello")
    env.backend.raise_backend = True
    with pytest.raises(gr.Error):
        app.retranslate_line(doc, 1, *ENGINE, *VIEW)


def test_retry_all_fixes_failed_lines(env):
    env.backend.refuse_words = ("bad",)
    *_, (_, _, _, doc, _) = _translate("good one\nbad one")
    assert not doc.complete and env.history.list() == []
    env.backend.refuse_words = ()
    *_, (_, status, doc, files) = list(app.retry_all(doc, *ENGINE, *VIEW))
    assert doc.complete and files
    assert len(env.history.list()) == 1


class _Sel:
    def __init__(self, index):
        self.index = index


def test_open_and_delete_history(env):
    _translate("hello world", title="Song")
    _, ids, *_ = app.history_view("ko")
    n = len(env.backend.calls)
    out = app.open_history(ids, "ko", *VIEW[:-1], _Sel([0, 0]))
    html, status, doc, files, sel = out[:5]
    assert doc.title == "Song" and sel == ids[0] and "hello" in html
    assert len(env.backend.calls) == n  # 저장된 결과를 그대로 연다
    with pytest.raises(gr.Error):
        app.open_history(ids, "ko", *VIEW[:-1], _Sel([5, 0]))
    assert app.delete_history(sel, "ko") is None
    assert env.history.list() == []
    with pytest.raises(gr.Error):
        app.delete_history(None, "ko")


def test_export_many(env):
    _translate("hello world", title="A")
    _translate("see you", title="B")
    _, ids, *_ = app.history_view("ko")
    paths = app.export_many(ids, [FMT_MOBILE, FMT_MD, FMT_ANKI], *VIEW)
    assert any(p.endswith(".zip") for p in paths) and any(p.endswith("_mobile.html") for p in paths)
    with pytest.raises(gr.Error):
        app.export_many([], [FMT_MD], *VIEW)
    with pytest.raises(gr.Error):
        app.export_many(ids, [], *VIEW)
    with pytest.raises(gr.Error):  # 목록에 없는 값(직접 입력)은 건너뛰고, 남는 곡이 없으면 오류
        app.export_many(["..\\..\\x", "C:evil"], [FMT_MD], *VIEW)


def test_restore_settings_fills_defaults():
    req = types.SimpleNamespace(headers={"accept-language": "ko-KR,ko;q=0.9"})
    out = app.restore_settings({"mode": "옛 화면 이름", "engine": "nope", "dict": "?"}, req)
    ui, target, engine = out[:3]
    assert (ui, target, engine) == ("ko", "ko", app.DEFAULT_SETTINGS["engine"])
    assert out[8] == "source"  # mode


def test_backend_error_type_is_reexported():
    # run_translate가 잡는 오류 종류가 엔진 모듈의 것과 같은지
    assert app.BackendError is BackendError
