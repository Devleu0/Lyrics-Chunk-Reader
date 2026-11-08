import app


def test_settings_secret_is_stable(tmp_path):
    key = app.settings_secret(tmp_path / "k" / "settings.key")
    assert key and app.settings_secret(tmp_path / "k" / "settings.key") == key  # 다시 켜도 같은 키
    assert app.settings_secret(tmp_path / "other.key") != key
