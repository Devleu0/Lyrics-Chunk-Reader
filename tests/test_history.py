import time

from lyrics_tool.cache import Cache, default_title


def test_save_list_update_delete():
    c = Cache(":memory:")
    a = c.save_history("", "first line\nsecond", "en", "ollama", "m", 8)
    time.sleep(0.01)
    b = c.save_history("노래 B", "다른 가사", "ja", "gemini", "g", 8)
    assert [h.id for h in c.list_history()] == [b, a]
    assert c.get_history(a).title == "first line"

    time.sleep(0.01)
    again = c.save_history("새 제목", "first line\nsecond", "en", "ollama", "m", 8)
    assert again == a  # 같은 가사·엔진·모델이면 갱신
    items = c.list_history()
    assert [h.id for h in items] == [a, b] and items[0].title == "새 제목"
    assert "새 제목 · m ·" in items[0].label

    c.delete_history(a)
    assert [h.id for h in c.list_history()] == [b]
    assert c.get_history(a) is None


def test_different_model_is_separate_entry():
    c = Cache(":memory:")
    c.save_history("", "x", "en", "ollama", "m1", 8)
    c.save_history("", "x", "en", "ollama", "m2", 8)
    assert len(c.list_history()) == 2


def test_default_title_truncates():
    assert default_title("\n\n" + "a" * 40) == "a" * 30 + "…"
    assert default_title("") == "제목 없음"
