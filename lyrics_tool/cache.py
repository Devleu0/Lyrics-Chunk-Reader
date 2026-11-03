"""번역 캐시 (SQLite 한 파일). 번역 히스토리는 history.py(곡마다 JSON 파일).

키 = (프롬프트 버전, 엔진, 모델, 원문 언어, 번역 언어, 구간 원문)의 해시.
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


def default_title(lyrics: str, empty: str = "Untitled") -> str:
    first = next((l.strip() for l in lyrics.splitlines() if l.strip()), empty)
    return first if len(first) <= 30 else first[:30] + "…"
