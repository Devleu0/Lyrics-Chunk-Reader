from lyrics_tool.backends import BackendError, OllamaBackend, _has_model


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
