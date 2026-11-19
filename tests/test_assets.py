"""브라우저 스크립트 문법 검사 — 자리표시자를 채운, 실제로 페이지에 들어가는 JS를 Node로 검사한다."""

import re
import shutil
import subprocess

import pytest

import app
from lyrics_tool import assets, render
from lyrics_tool.core import Translator
from lyrics_tool.render import ViewOptions, to_mobile_html

from test_core import FakeBackend

NODE = shutil.which("node")


def _scripts() -> dict[str, str]:
    doc = Translator(FakeBackend()).translate("a b\nc d", "en")
    page = to_mobile_html([(doc, "")], "both", "line", ViewOptions(), "t")
    mobile = re.search(r"<script>(.*)</script>", page, re.S).group(1)
    # 함수 식은 괄호로 감싸 하나의 식 문장으로 검사한다
    return {
        "app.js": f"({app.APP_JS});",
        "image.js": f"({app.IMAGE_JS});",
        "tts.js": f"({render.TTS_JS});",
        "fit.js": f"({render.FIT_JS});",
        "mobile (assembled)": mobile,
        "play": f"({app.PLAY_JS});",
        "say-check": f"({app.SAY_CHECK_JS});",
    }


def test_no_placeholder_left():
    for name, js in _scripts().items():
        assert not re.search(r"%(TTS|FIT|MIN)%", js), name


@pytest.mark.skipif(NODE is None, reason="node가 없으면 건너뛴다")
@pytest.mark.parametrize("name", list(_scripts()))
def test_script_syntax(name, tmp_path):
    path = tmp_path / "check.js"
    path.write_text(_scripts()[name], encoding="utf-8")
    r = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr


def test_assets_are_files():
    # 모든 CSS·JS가 파일에서 오는지 (파이썬 문자열에 다시 넣지 않도록)
    names = {p.name for p in assets.DIR.iterdir() if p.suffix in (".css", ".js")}
    assert {"view.css", "mobile.css", "app.css", "tts.js", "fit.js", "mobile.js", "app.js", "image.js"} <= names
