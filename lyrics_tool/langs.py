"""지원 언어 목록과 원문 언어 자동 감지.

원문·번역 언어는 같은 목록을 쓴다. 프롬프트에는 영어 이름을 넣는다(모델이 가장 잘 알아듣는다).
"""

from __future__ import annotations

import re

# 코드: (영어 이름, 한국어 이름)
LANGS: dict[str, tuple[str, str]] = {
    "en": ("English", "영어"),
    "ja": ("Japanese", "일본어"),
    "zh": ("Chinese", "중국어"),
    "ko": ("Korean", "한국어"),
    "es": ("Spanish", "스페인어"),
    "fr": ("French", "프랑스어"),
    "de": ("German", "독일어"),
    "pt": ("Portuguese", "포르투갈어"),
    "it": ("Italian", "이탈리아어"),
    "ru": ("Russian", "러시아어"),
    "vi": ("Vietnamese", "베트남어"),
    "th": ("Thai", "태국어"),
    "id": ("Indonesian", "인도네시아어"),
}


def lang_name(code: str, ui: str = "en") -> str:
    names = LANGS.get(code)
    if not names:
        return code
    return names[1] if ui == "ko" else names[0]


_KANA = re.compile(r"[぀-ヿ]")
_SCRIPTS = {
    "ko": (re.compile(r"[가-힣]"), 3),  # 한 글자가 라틴 문자 여러 개 몫
    "zh": (re.compile(r"[㐀-䶿一-鿿]"), 3),
    "ru": (re.compile(r"[Ѐ-ӿ]"), 1),
    "th": (re.compile(r"[฀-๿]"), 1),
    "latin": (re.compile(r"[A-Za-zÀ-ɏḀ-ỿ]"), 1),
}
_VI = re.compile(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.I)
_STOPWORDS = {
    "en": "the you and i me my is are to of in it that your we be don't not all so love",
    "es": "el los las y que en por con mi tu te me es una un yo como para amor corazón pero",
    "fr": "le les des et je tu que qui pas ne mon ma est dans une moi toi pour avec c'est",
    "de": "der die das und ich du nicht ist ein eine mich dich mit auf zu wir sie mein dein",
    "pt": "o os as e que não eu você meu minha com em um uma é do da pra coração",
    "it": "il di che e non io tu mi ti un una è per con sono ma amore cuore del",
    "id": "yang dan aku kau kamu tak tidak ini itu di ke dari cinta hati akan untuk dengan",
}
_WORDS = {k: set(v.split()) for k, v in _STOPWORDS.items()}
_TOKEN = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?", re.UNICODE)


def detect_language(text: str) -> str:
    """가나가 있으면 일본어. 그 밖에는 문자 체계로 고르고, 라틴 문자면 자주 쓰는 단어로 언어를 추정한다."""
    if _KANA.search(text):
        return "ja"
    scores = {k: len(rx.findall(text)) * w for k, (rx, w) in _SCRIPTS.items()}
    script = max(scores, key=scores.get)
    if script != "latin" and scores[script]:
        return script
    if len(_VI.findall(text)) >= 3:
        return "vi"
    words = [w.lower() for w in _TOKEN.findall(text)]
    hits = {lang: sum(w in ws for w in words) for lang, ws in _WORDS.items()}
    best = max(hits, key=hits.get)
    return best if hits[best] >= 2 and hits[best] > hits["en"] else "en"  # 한두 단어 우연 일치는 영어로
