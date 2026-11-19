import app


def test_settings_secret_is_stable(tmp_path):
    key = app.settings_secret(tmp_path / "k" / "settings.key")
    assert key and app.settings_secret(tmp_path / "k" / "settings.key") == key  # 다시 켜도 같은 키
    assert app.settings_secret(tmp_path / "other.key") != key


def test_launch_options_auth_and_warning(caplog):
    assert app.launch_options({}) == {"server_name": "127.0.0.1"}
    assert app.launch_options({"HOST": "0.0.0.0", "LYRICS_AUTH": "me:pw"}) == {
        "server_name": "0.0.0.0", "auth": ("me", "pw")}
    with caplog.at_level("WARNING"):
        assert "auth" not in app.launch_options({"HOST": "0.0.0.0", "LYRICS_AUTH": "nopassword"})
    assert "LYRICS_AUTH" in caplog.text


def test_prune_exports(tmp_path):
    import os

    old, new = tmp_path / "a" / "old.mp3", tmp_path / "new.html"
    old.parent.mkdir()
    old.write_text("x")
    new.write_text("y")
    os.utime(old, (1000, 1000))
    assert app.prune_exports(tmp_path, max_age=3600, now=10_000) == 1
    assert not old.exists() and new.exists()
    assert app.prune_exports(tmp_path / "missing") == 0
