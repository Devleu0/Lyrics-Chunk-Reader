"""README 스크린샷용 데모 히스토리를 만든다 — 엔진을 부르지 않고, 직접 쓴 결과로 저장한다.

가사는 이 데모를 위해 새로 쓴 문장이다. 사용:
    python tools/screenshots/make_history.py <폴더>     (기본: exports/demo)
<폴더>/history-en, <폴더>/history-ko 에 곡마다 JSON을 만든다. 앱은 LYRICS_HISTORY_DIR로 그 폴더를 가리킨다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lyrics_tool.backends import Backend  # noqa: E402
from lyrics_tool.core import Translator  # noqa: E402
from lyrics_tool.history import History  # noqa: E402

MODEL = "gemini-3.5-flash-lite"

# 곡: (제목, [(원문 줄, [(어구, 한국어, 영어)], 한국어 직역, 영어 직역) 또는 ""(빈 줄)], [(첫 줄, 끝 줄, 한국어, 영어)])
SONGS = [
    ("夜明けの駅で君を待ってた", [
        ("夜明けの駅で君を待ってた",
         [("夜明けの", "새벽의", "at dawn"), ("駅で", "역에서", "at the station"), ("君を", "너를", "you"),
          ("待ってた", "기다리고 있었어", "was waiting for")],
         "새벽 역에서 너를 기다리고 있었어", "I was waiting for you at the station at dawn"),
        ("冷たい風が頬をなでる",
         [("冷たい", "차가운", "cold"), ("風が", "바람이", "wind"), ("頬を", "뺨을", "my cheek"),
          ("なでる", "쓰다듬어", "strokes")],
         "차가운 바람이 뺨을 쓰다듬어", "A cold wind strokes my cheek"),
        ("言えなかった言葉を",
         [("言えなかった", "말하지 못한", "that I couldn't say"), ("言葉を", "말을", "the words")],
         "말하지 못한 말을", "the words I couldn't say"),
        ("ポケットにしまったまま",
         [("ポケットに", "주머니에", "in my pocket"), ("しまったまま", "넣어 둔 채로", "still tucked away")],
         "주머니에 넣어 둔 채로", "still tucked away in my pocket"),
        "",
        ("二人で歩いた坂道を",
         [("二人で", "둘이서", "together"), ("歩いた", "걸었던", "we walked"), ("坂道を", "비탈길을", "the slope")],
         "둘이서 걸었던 비탈길을", "the slope we walked together"),
        ("今日はひとりで登ってく",
         [("今日は", "오늘은", "today"), ("ひとりで", "혼자서", "alone"), ("登ってく", "올라가", "I climb")],
         "오늘은 혼자서 올라가", "today I climb it alone"),
    ], [(3, 4, "말하지 못한 말을 주머니에 넣어 둔 채로", "with the words I couldn't say still tucked away in my pocket"),
        (6, 7, "둘이서 걸었던 비탈길을 오늘은 혼자서 올라가", "today I climb alone the slope we walked together")]),
    ("放課後の窓に", [
        ("放課後の窓に夕日が落ちて",
         [("放課後の", "방과 후의", "after school"), ("窓に", "창문에", "on the window"), ("夕日が", "석양이", "the evening sun"),
          ("落ちて", "지고", "falls, and")],
         "방과 후 창문에 석양이 지고", "The evening sun falls on the window after school"),
        ("黒板の文字が少しにじむ",
         [("黒板の", "칠판의", "on the blackboard"), ("文字が", "글씨가", "the letters"), ("少し", "조금", "a little"),
          ("にじむ", "번진다", "blur")],
         "칠판 글씨가 조금 번진다", "The letters on the blackboard blur a little"),
        ("また明日って手を振った",
         [("また明日って", "내일 또 보자며", "saying \"see you tomorrow\""), ("手を", "손을", "my hand"),
          ("振った", "흔들었다", "I waved")],
         "내일 또 보자며 손을 흔들었다", "I waved, saying \"see you tomorrow\""),
    ], []),
]


class ScriptedBackend(Backend):
    """프롬프트의 [INPUT] 줄을 SONGS에서 찾아 그대로 답한다."""

    def __init__(self, target: str):
        super().__init__(model=MODEL)
        self.target = target
        self.lines, self.sents = {}, []
        for _, rows, sents in SONGS:
            for row in rows:
                if row:
                    src, chunks, ko, en = row
                    self.lines[src] = ([(s, k if target == "ko" else e) for s, k, e in chunks], ko if target == "ko" else en)
            texts = [r[0] if r else "" for r in rows]
            self.sents += [(texts[a - 1], texts[b - 1], ko if target == "ko" else en) for a, b, ko, en in sents]

    def chat(self, system, user):
        body = user.split("[INPUT]\n", 1)[1].split("\n\n[NOTE]")[0]
        lines = [(int(a), b) for a, b in (l.split(": ", 1) for l in body.splitlines())]
        by_text = {t: i for i, t in lines}
        out = [{"i": i, "chunks": [{"s": s, "t": g} for s, g in self.lines[t][0]], "tr": self.lines[t][1]}
               for i, t in lines]
        sents = [{"from": by_text[a], "to": by_text[b], "tr": tr} for a, b, tr in self.sents
                 if a in by_text and b in by_text]
        return json.dumps({"lines": out, "sentences": sents}, ensure_ascii=False)


def main(folder: Path) -> None:
    from lyrics_tool.export import song_meta
    from lyrics_tool.i18n import t
    from lyrics_tool.render import FIT_JS, MODE_BOTH, MODE_SOURCE, UNIT_LINE, ViewOptions, to_image_html, to_mobile_html

    files = folder / "files"
    files.mkdir(parents=True, exist_ok=True)
    for target in ("en", "ko"):
        h = History(folder / f"history-{target}")
        docs = []
        for i, (title, rows, _) in enumerate(SONGS):
            lyrics = "\n".join(r[0] if r else "" for r in rows)
            doc = Translator(ScriptedBackend(target), target=target).translate(lyrics, "ja")
            doc.title = title
            # 첫 곡이 목록 맨 위에 오도록 저장 시각을 뒤로 민다
            assert h.save(doc, "gemini", MODEL, 8, saved=1_794_900_000 - i * 600), title
            docs.append(doc)
        print(target, [e.title for e in h.list()])

        # 내보내기 화면용: 두 곡 모바일 HTML, 이미지로 그릴 조각(앱의 IMAGE_JS처럼 FIT_JS로 폭을 맞춘다)
        ui = target
        opts = ViewOptions(ui=ui)
        book = t(ui, "many_book", n=len(docs), date="2026-11-19")
        (files / f"book-{ui}.html").write_text(
            to_mobile_html([(d, song_meta(d, MODE_BOTH, UNIT_LINE, ui, view=False)) for d in docs], MODE_BOTH,
                           UNIT_LINE, opts, book), encoding="utf-8")
        img = to_image_html(docs[0], MODE_SOURCE, UNIT_LINE, opts, docs[0].title,
                            song_meta(docs[0], MODE_SOURCE, UNIT_LINE, ui), "phone", dark=True)
        (files / f"image-{ui}.html").write_text(
            f'<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0;background:#161616">{img}'
            f"<script>({FIT_JS})(document)</script></body></html>", encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "exports/demo"))
