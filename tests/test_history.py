import json
import time

from lyrics_tool.cache import Cache, default_title
from lyrics_tool.core import Translator, build_user_prompt
from lyrics_tool.history import History, import_from_cache

from test_core import FakeBackend


def test_saves_only_complete_translations(tmp_path):
    h = History(tmp_path)
    ok = Translator(FakeBackend()).translate("hello\n\nworld", "en")
    ok.title = "Song A"
    assert h.save(ok, "ollama", "m", 8) == "Song_A-" + h.list()[0].id.split("-")[-1]

    bad = Translator(FakeBackend(refuse_words=("BAD",)), max_attempts=1).translate("fine\nBAD", "en")
    assert h.save(bad, "ollama", "m", 8) is None  # 실패한 줄이 있으면 저장하지 않음
    pending = Translator(FakeBackend()).prepare("not yet", "en")
    assert h.save(pending, "ollama", "m", 8) is None  # 번역 전·중단된 문서도
    assert [e.title for e in h.list()] == ["Song A"]


def test_load_restores_without_backend(tmp_path):
    h = History(tmp_path)
    doc = Translator(FakeBackend(group=True)).translate("a >\nb\n\nc", "en")
    doc.title = "제목"
    entry_id = h.save(doc, "gemini", "g", 8)
    back, meta = h.load(entry_id)
    assert [l.tr for l in back.lines()] == [l.tr for l in doc.lines()]
    assert [(s.start, s.end, s.tr) for s in back.sentences()] == [(s.start, s.end, s.tr) for s in doc.sentences()]
    assert back.title == "제목" and back.target == "ko" and meta["engine"] == "gemini" and meta["lyrics"] == "a >\nb\n\nc"
    e = h.list()[0]
    assert (e.lang, e.target, e.lines, e.model) == ("en", "ko", 3, "g")


def test_same_song_overwrites_and_retitles(tmp_path):
    h = History(tmp_path)
    doc = Translator(FakeBackend()).translate("x", "en")
    doc.title = "old"
    h.save(doc, "ollama", "m", 8, saved=1)
    doc.title = "new"
    h.save(doc, "ollama", "m", 8, saved=2)
    assert [e.title for e in h.list()] == ["new"] and len(list(tmp_path.glob("*.json"))) == 1
    other = Translator(FakeBackend(), target="ja").translate("x", "en")
    h.save(other, "ollama", "m", 8, saved=3)  # 번역 언어가 다르면 다른 항목
    assert [e.target for e in h.list()] == ["ja", "ko"]


def test_list_skips_broken_files_and_delete(tmp_path):
    h = History(tmp_path)
    (tmp_path / "junk.json").write_text("{not json", encoding="utf-8")
    doc = Translator(FakeBackend()).translate("y", "en")
    entry_id = h.save(doc, "ollama", "m", 8)
    assert [e.id for e in h.list()] == [entry_id]
    h.delete(entry_id)
    assert h.list() == []


def test_import_old_sqlite_history(tmp_path):
    cache = Cache(":memory:")
    conn = cache._conn
    conn.execute("CREATE TABLE history (id INTEGER PRIMARY KEY, title TEXT, lyrics TEXT, lang TEXT, engine TEXT,"
                 " model TEXT, batch INTEGER, updated REAL, target TEXT)")
    # 캐시에 결과가 있는 곡 하나 + 결과가 없는(실패했거나 지워진) 곡 하나
    fb = FakeBackend()
    fb.kind, fb.model = "ollama", "qwen3:8b"
    Translator(fb, cache=cache).translate("kept song", "en")
    conn.execute("INSERT INTO history VALUES (1, 'kept', 'kept song', 'en', 'ollama', 'qwen3:8b', 8, 100, 'ko')")
    conn.execute("INSERT INTO history VALUES (2, 'lost', 'never translated', 'en', 'ollama', 'qwen3:8b', 8, 200, 'ko')")
    h = History(tmp_path)
    assert import_from_cache(cache, h) == 1
    assert [e.title for e in h.list()] == ["kept"]
    assert import_from_cache(cache, h) == 0  # 표를 지웠으니 다시 돌지 않음
    data = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert data["saved"] == 100


def test_import_recovers_prompt_v2_results(tmp_path):
    from lyrics_tool.cache import make_key

    cache = Cache(":memory:")
    old = {"lines": [{"chunks": [{"s": "hi", "k": "안녕"}], "ko": "안녕", "error": ""}], "sentences": [[0, 0, "안녕"]]}
    cache.put(make_key(2, "Gemini", "g", "en", ["hi"]), old)
    cache._conn.execute("CREATE TABLE history (title TEXT, lyrics TEXT, lang TEXT, engine TEXT, model TEXT,"
                        " batch INTEGER, updated REAL)")  # target 열이 없던 시절
    cache._conn.execute("INSERT INTO history VALUES ('v2 song', 'hi', 'en', 'gemini', 'g', 8, 5)")
    h = History(tmp_path)
    assert import_from_cache(cache, h) == 1
    doc, _ = h.load(h.list()[0].id)
    line = doc.lines()[0]
    assert (line.chunks[0].s, line.chunks[0].t, line.tr) == ("hi", "안녕", "안녕")
    assert cache.get(doc.segments[0].key)["lines"][0]["tr"] == "안녕"  # 새 키로도 캐시에 들어감


def test_korean_source_uses_eojeol_guide():
    assert "eojeol" in build_user_prompt([(1, "너를 기다려")], "ko", target="en")


def test_default_title_truncates():
    assert default_title("\n\n" + "a" * 40) == "a" * 30 + "…"
    assert default_title("") == "Untitled"
    assert time.time() > 0
