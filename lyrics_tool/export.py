"""내보내기 파일 만들기 — 곡 하나 또는 여러 곡을 한꺼번에.

형식 (값은 코드, 화면 이름은 i18n `fmt_<값>`)
  FMT_MOBILE : 폰에서 읽기 좋은 단독 HTML. 여러 곡이면 목차가 붙은 한 파일로 묶는다
  FMT_PRINT  : 인쇄·PDF 저장용 HTML (곡마다)
  FMT_MD     : Markdown (곡마다)
  FMT_JSON   : 결과 전체 JSON (곡마다)
이미지(PNG)는 브라우저가 그리므로 여기서 만들지 않는다 (render.to_image_html + app.IMAGE_JS).
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from .core import Doc
from .i18n import t
from .langs import lang_name
from .render import (
    MODE_SOURCE, ViewOptions, mode_label, to_markdown, to_mobile_html, to_print_html, unit_label,
)

FMT_MOBILE = "mobile"
FMT_PRINT = "print"
FMT_MD = "md"
FMT_JSON = "json"
FORMATS = [FMT_MOBILE, FMT_PRINT, FMT_MD, FMT_JSON]


def safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("._")[:40] or "lyrics"


def song_meta(doc: Doc, mode: str, unit: str, ui: str, view: bool = True) -> str:
    """곡 설명 한 줄: 언어 · 보기 방식 · 직역 단위. 모바일 HTML은 보기 방식을 읽는 사람이 바꾸므로 view=False."""
    parts = [f"{lang_name(doc.lang, ui)} → {lang_name(doc.target, ui)}"]
    if not view:
        return parts[0]
    parts.append(mode_label(mode, ui))
    if mode != MODE_SOURCE:
        parts.append(unit_label(unit, ui))
    return " · ".join(parts)


def _tag(mode: str, unit: str) -> str:
    return mode if mode == MODE_SOURCE else f"{mode}-{unit}"


def song_files(doc: Doc, mode: str, unit: str, opts: ViewOptions, formats=FORMATS) -> dict[str, str]:
    """곡 하나의 내보내기 파일 {파일 이름: 내용}."""
    ui = opts.ui
    base, tag = safe_name(doc.title), _tag(mode, unit)
    title = doc.title or t(ui, "app_title")
    meta = song_meta(doc, mode, unit, ui)
    out: dict[str, str] = {}
    if FMT_MOBILE in formats:
        out[f"{base}_mobile.html"] = to_mobile_html([(doc, song_meta(doc, mode, unit, ui, view=False))], mode, unit,
                                                    opts, title)
    if FMT_PRINT in formats:
        out[f"{base}_{tag}_print.html"] = to_print_html(doc, mode, unit, opts, title, meta)
    if FMT_MD in formats:
        out[f"{base}_{tag}.md"] = to_markdown(doc, mode, unit, opts)
    if FMT_JSON in formats:
        out[f"{base}_data.json"] = doc.to_json()
    return out


def write_song(doc: Doc, mode: str, unit: str, opts: ViewOptions, out_dir: Path) -> list[str]:
    """지금 연 곡의 파일을 모두 쓰고 경로를 돌려준다 (모바일 HTML이 먼저)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, text in song_files(doc, mode, unit, opts).items():
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        paths.append(str(path))
    return paths


def write_bundle(docs: list[Doc], mode: str, unit: str, opts: ViewOptions, formats, out_dir: Path,
                 name: str) -> list[str]:
    """여러 곡을 한꺼번에 내보낸다. 곡별 파일은 ZIP 하나에 `01_제목/`처럼 곡마다 폴더로 넣는다.

    모바일 형식을 고르면 모든 곡을 목차가 붙은 HTML 한 파일로 묶어 ZIP 안과 밖에 둘 다 둔다
    (폰으로 바로 보내기 쉽게). 모바일만 고르면 ZIP 없이 그 HTML만 만든다.
    돌려주는 경로: [ZIP(곡별 형식이 있으면), 묶음 모바일 HTML(있으면)].
    """
    ui = opts.ui
    formats = [f for f in FORMATS if f in (formats or [])]
    if not docs or not formats:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    base = safe_name(name)
    out: list[str] = []
    book = None
    if FMT_MOBILE in formats:
        book = to_mobile_html([(d, song_meta(d, mode, unit, ui, view=False)) for d in docs], mode, unit, opts, name)
        book_path = out_dir / f"{base}_mobile.html"
        book_path.write_text(book, encoding="utf-8")
        out.append(str(book_path))
    per_song = [f for f in formats if f != FMT_MOBILE]
    if not per_song:
        return out  # 모바일 묶음만 고르면 ZIP 없이 HTML 한 파일
    zip_path = out_dir / f"{base}.zip"
    width = len(str(len(docs)))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        if book is not None:
            z.writestr(f"{base}_mobile.html", book)
        for i, doc in enumerate(docs, 1):
            folder = f"{i:0{width}d}_{safe_name(doc.title)}"
            for fname, text in song_files(doc, mode, unit, opts, per_song).items():
                z.writestr(f"{folder}/{fname}", text)
    return [str(zip_path)] + out
