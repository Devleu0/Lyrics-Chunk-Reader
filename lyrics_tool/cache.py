"""번역 캐시와 최근 번역 목록 (SQLite 한 파일).

키 = (프롬프트 버전, 엔진, 모델, 언어, 구간 원문)의 해시.
- 같은 곡을 다시 열거나 반복되는 연(후렴)은 LLM을 다시 부르지 않는다.
- 엔진·모델이 다르면 다른 키 → 엔진을 바꿔 비교 번역할 수 있다.
- 사용자가 고친 결과도 같은 키에 덮어써 다음에 그대로 나온다.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(os.environ.get("LYRICS_CACHE", Path.home() / ".lyrics-jikdok" / "cache.db"))


def make_key(*parts: object) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Cache:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # Gradio는 요청마다 다른 스레드에서 실행되므로 스레드 공유 + 락
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS segments ("
                " key TEXT PRIMARY KEY, value TEXT NOT NULL,"
                " updated TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS history ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, lyrics TEXT NOT NULL,"
                " lang TEXT NOT NULL, engine TEXT NOT NULL, model TEXT NOT NULL, batch INTEGER NOT NULL,"
                " updated REAL NOT NULL,"
                " UNIQUE(lyrics, engine, model, batch))"
            )
            self._conn.commit()

    def get(self, key: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM segments WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO segments(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated = CURRENT_TIMESTAMP",
                (key, json.dumps(value, ensure_ascii=False)),
            )
            self._conn.commit()

    def clear(self) -> int:
        with self._lock:
            n = self._conn.execute("DELETE FROM segments").rowcount
            self._conn.commit()
        return n

    def __len__(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]

    # ---------------------------------------------------------------- 최근 번역

    def save_history(self, title: str, lyrics: str, lang: str, engine: str, model: str, batch: int) -> int:
        """같은 가사·엔진·모델·배치면 제목과 시각만 갱신한다. 항목 id를 반환."""
        title = title.strip() or default_title(lyrics)
        with self._lock:
            self._conn.execute(
                "INSERT INTO history(title, lyrics, lang, engine, model, batch, updated) "
                "VALUES(?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(lyrics, engine, model, batch) DO UPDATE SET "
                " title = excluded.title, lang = excluded.lang, updated = excluded.updated",
                (title, lyrics, lang, engine, model, int(batch), time.time()),
            )
            row = self._conn.execute(
                "SELECT id FROM history WHERE lyrics = ? AND engine = ? AND model = ? AND batch = ?",
                (lyrics, engine, model, int(batch)),
            ).fetchone()
            self._conn.commit()
        return row[0]

    def list_history(self, limit: int = 30) -> list["HistoryItem"]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, title, lyrics, lang, engine, model, batch, updated FROM history "
                "ORDER BY updated DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [HistoryItem(*r) for r in rows]

    def get_history(self, item_id: int) -> "HistoryItem | None":
        with self._lock:
            r = self._conn.execute(
                "SELECT id, title, lyrics, lang, engine, model, batch, updated FROM history WHERE id = ?",
                (item_id,),
            ).fetchone()
        return HistoryItem(*r) if r else None

    def delete_history(self, item_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM history WHERE id = ?", (item_id,))
            self._conn.commit()


@dataclass
class HistoryItem:
    id: int
    title: str
    lyrics: str
    lang: str
    engine: str
    model: str
    batch: int
    updated: float

    @property
    def label(self) -> str:
        when = time.strftime("%m/%d %H:%M", time.localtime(self.updated))
        return f"{self.title} · {self.model} · {when}"


def default_title(lyrics: str) -> str:
    first = next((l.strip() for l in lyrics.splitlines() if l.strip()), "제목 없음")
    return first if len(first) <= 30 else first[:30] + "…"
