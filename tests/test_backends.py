import pytest
import requests

from lyrics_tool.backends import GEMINI_DEFAULT_MODEL, BackendError, OllamaBackend, _has_model, make_backend


def test_has_model_handles_latest_tag():
    assert _has_model(["qwen3:8b", "gemma3:latest"], "gemma3")
    assert _has_model(["qwen3:8b"], "qwen3:8b")
    assert not _has_model(["qwen3:8b"], "qwen3:14b")
    assert _has_model([], "anything")


def test_check_reports_missing_model_and_connection(monkeypatch):
    b = OllamaBackend(model="qwen3:14b")
    monkeypatch.setattr(b, "fetch_models", lambda: ["qwen3:8b"])
    r = b.check()
    assert not r.ok and "ollama pull qwen3:14b" in r.message and r.models == ["qwen3:8b"]

    def down():
        raise BackendError("연결할 수 없습니다")

    monkeypatch.setattr(b, "fetch_models", down)
    assert not b.check().ok

    b.model = "qwen3:8b"
    monkeypatch.setattr(b, "fetch_models", lambda: ["qwen3:8b"])
    assert b.check().ok


class _Resp:
    def __init__(self, status, text="{}", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}

    def json(self):
        if self.status_code >= 400:
            import json
            return json.loads(self.text)
        return {"ok": True}


def _fake_post(monkeypatch, responses):
    calls, waits = [], []

    def post(url, **kw):
        calls.append(url)
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr("lyrics_tool.backends.requests.post", post)
    monkeypatch.setattr("lyrics_tool.backends.time.sleep", waits.append)
    return calls, waits


def test_post_retries_transient_errors(monkeypatch):
    gemini_429 = '{"error": {"details": [{"retryDelay": "7s"}]}}'
    calls, waits = _fake_post(monkeypatch, [
        requests.ConnectionError(), _Resp(503), _Resp(429, gemini_429), _Resp(200)])
    assert OllamaBackend(model="m", retries=3)._post("u") == {"ok": True}
    assert len(calls) == 4 and len(waits) == 3
    assert 2 <= waits[0] < 3 and 4 <= waits[1] < 5 and waits[2] == 7


def test_post_gives_up(monkeypatch):
    busy = '{"error": {"code": 503, "message": "high demand"}}'
    calls, _ = _fake_post(monkeypatch, [_Resp(503), _Resp(503, busy)])
    with pytest.raises(BackendError, match="503: high demand .2회 시도"):
        OllamaBackend(model="m", retries=1)._post("u")
    calls, _ = _fake_post(monkeypatch, [_Resp(400, "bad")])  # 요청 자체가 틀리면 재시도 안 함
    with pytest.raises(BackendError, match="400: bad$"):
        OllamaBackend(model="m", retries=3)._post("u")
    calls, _ = _fake_post(monkeypatch, [_Resp(429, "{}", {"Retry-After": "3600"})])  # 일일 한도 등
    with pytest.raises(BackendError):
        OllamaBackend(model="m", retries=3)._post("u")
    assert len(calls) == 1


def test_empty_env_values_use_defaults(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "")
    monkeypatch.setenv("OLLAMA_HOST", " ")
    assert make_backend("gemini").model == GEMINI_DEFAULT_MODEL
    assert make_backend("ollama", retries=5).host == "http://localhost:11434"
    assert make_backend("ollama", retries=5).retries == 5
