import app
from lyrics_tool.core import Translator
from lyrics_tool.history import History

from test_core import FakeBackend

VIEW = ["source", "line", 16, True, False, False, "intl", "ko"]  # app.py의 V 순서


def _song(h, text, title, saved):
    doc = Translator(FakeBackend()).translate(text, "en")
    doc.title = title
    return h.save(doc, "ollama", "m", 8, saved=saved)


def test_offline_pack_sends_only_changes(tmp_path, monkeypatch):
    h = History(tmp_path)
    monkeypatch.setattr(app, "HISTORY", h)
    a = _song(h, "hello", "A", 100)
    b = _song(h, "world", "B", 200)

    sent, pack = app.offline_pack(None, *VIEW)
    assert pack["reset"] and pack["ids"] == [b, a] and set(pack["add"]) == {a, b}
    assert pack["add"][a]["title"] == "A" and 'class="jk-s"' in pack["add"][a]["html"]
    assert pack["msg"].startswith("앱 서버가 꺼져") and 'class="jk-wrap" data-lang' in pack["add"][a]["html"]

    sent, pack = app.offline_pack(sent, *VIEW)  # 그대로면 아무것도 다시 보내지 않는다
    assert not pack["reset"] and pack["add"] == {}

    _song(h, "world", "B", 300)  # 다시 저장된 곡만
    h.delete(a)
    sent, pack = app.offline_pack(sent, *VIEW)
    assert list(pack["add"]) == [b] and pack["ids"] == [b] and set(sent["have"]) == {b}

    sent, pack = app.offline_pack(sent, *(["both"] + VIEW[1:]))  # 보기 설정이 바뀌면 전부
    assert pack["reset"] and list(pack["add"]) == [b]
