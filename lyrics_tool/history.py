"""번역 히스토리 — 끝까지 제대로 번역된 곡만 곡마다 JSON 파일 하나로 저장한다.

위치: 기본 <프로젝트>/history/ (환경변수 LYRICS_HISTORY_DIR로 변경). 파일을 직접 열어 보거나 지워도 된다.
파일 이름: <제목>-<가사·번역 언어 해시 8자리>.json — 같은 가사를 같은 언어로 다시 번역하면 덮어쓴다.
파일에는 결과 전체(Doc.dump)가 들어 있어, 불러올 때 엔진을 부르거나 캐시를 찾지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .core import Doc

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "history"
FORMAT = 1


def default_dir() -> Path:
    return Path(os.environ.get("LYRICS_HISTORY_DIR") or DEFAULT_DIR).expanduser()


@dataclass
class Entry:
    id: str  # 파일 이름(확장자 제외)
    title: str
    lang: str
    target: str
    engine: str
    model: str
    lines: int
    saved: float

    @property
    def when(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.saved))


def _slug(title: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", title).strip("._")
    return s[:40] or "untitled"


def song_hash(lyrics: str, target: str) -> str:
    return hashlib.sha256(f"{target}\n{lyrics.strip()}".encode("utf-8")).hexdigest()[:8]


class History:
    def __init__(self, folder: str | Path | None = None):
        self.dir = Path(folder).expanduser() if folder else default_dir()

    def _path(self, entry_id: str) -> Path:
        if not re.fullmatch(r"[^\\/]+", entry_id):  # 폴더 밖 경로 차단
            raise KeyError(entry_id)
        return self.dir / f"{entry_id}.json"

    def save(self, doc: Doc, engine: str, model: str, batch: int, saved: float | None = None) -> str | None:
        """끝까지 번역된 문서만 저장하고 항목 id를 돌려준다. 미완성이면 저장하지 않고 None."""
        if not doc.complete:
            return None
        lyrics = "\n".join(doc.sources)
        h = song_hash(lyrics, doc.target)
        self.dir.mkdir(parents=True, exist_ok=True)
        for old in self.dir.glob(f"*-{h}.json"):  # 제목이 바뀌었으면 예전 파일을 지운다
            old.unlink()
        entry_id = f"{_slug(doc.title)}-{h}"
        data = {"format": FORMAT, "saved": saved or time.time(), "engine": engine, "model": model,
                "batch": int(batch), "lyrics": lyrics, "doc": doc.dump()}
        tmp = self._path(entry_id).with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self._path(entry_id))
        return entry_id

    def list(self, limit: int = 200) -> list[Entry]:
        out = []
        for p in self.dir.glob("*.json") if self.dir.exists() else []:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                doc = d["doc"]
                out.append(Entry(p.stem, doc.get("title") or p.stem, doc["lang"], doc.get("target", "ko"),
                                 d.get("engine", ""), d.get("model", ""),
                                 sum(1 for s in doc["sources"] if s.strip()), float(d.get("saved", p.stat().st_mtime))))
            except (OSError, ValueError, KeyError, TypeError):
                continue  # 손상되었거나 다른 파일은 건너뛴다
        out.sort(key=lambda e: e.saved, reverse=True)
        return out[:limit]

    def load(self, entry_id: str) -> tuple[Doc, dict]:
        """(문서, 메타데이터: engine·model·batch·lyrics·saved)"""
        d = json.loads(self._path(entry_id).read_text(encoding="utf-8"))
        return Doc.restore(d["doc"]), {k: v for k, v in d.items() if k != "doc"}

    def delete(self, entry_id: str) -> None:
        self._path(entry_id).unlink(missing_ok=True)


_V2_NAMES = {"ollama": "Ollama", "gemini": "Gemini", "openai": "OpenAI 호환"}


def _fill_from_v2(cache, doc: Doc, engine: str, model: str) -> None:
    """프롬프트 v2(한국어 전용, 필드 ko/k) 캐시 결과로 빈 구간을 채우고, 새 키로도 캐시에 넣는다."""
    from .cache import make_key
    from .core import SegResult

    for seg in doc.segments:
        if seg.key in doc.results:
            continue
        old = cache.get(make_key(2, _V2_NAMES.get(engine, engine), model, doc.lang, doc.texts(seg)))
        if not old:
            continue
        res = SegResult.from_dict({
            "lines": [{"chunks": [{"s": c["s"], "t": c.get("k", "")} for c in l["chunks"]],
                       "tr": l.get("ko", ""), "error": l.get("error", "")} for l in old["lines"]],
            "sentences": old["sentences"],
        })
        doc.results[seg.key] = res
        if res.ok:
            cache.put(seg.key, res.to_dict())


def import_from_cache(cache, history: History) -> int:
    """예전 버전(캐시 DB의 history 표)의 항목 중 캐시에 결과가 모두 남아 있는 곡만 파일로 옮긴다.

    옮긴 뒤 표를 비워 다시 실행되지 않게 한다. 결과가 없거나 실패한 곡은 버린다(다시 번역하지 않는다).
    """
    from .backends import make_backend
    from .core import Translator

    conn = cache._conn
    with cache._lock:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "history" not in tables:
            return 0
        cols = {r[1] for r in conn.execute("PRAGMA table_info(history)")}
        target_col = "target" if "target" in cols else "'ko'"
        rows = conn.execute(
            f"SELECT title, lyrics, lang, engine, model, batch, updated, {target_col} FROM history"
        ).fetchall()
    moved = 0
    for title, lyrics, lang, engine, model, batch, updated, target in rows:
        try:
            tr = Translator(make_backend(engine, model), batch_size=int(batch), cache=cache, target=target)
        except ValueError:
            continue
        doc = tr.prepare(lyrics, lang)
        doc.title = title
        if not doc.complete and target == "ko":
            _fill_from_v2(cache, doc, engine, tr.backend.model)
        if history.save(doc, engine, tr.backend.model, batch, saved=updated):
            moved += 1
    with cache._lock:
        conn.execute("DROP TABLE history")
        conn.commit()
    return moved
