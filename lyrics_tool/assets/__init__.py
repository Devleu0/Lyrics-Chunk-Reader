"""화면·내보내기 HTML에 넣는 CSS·브라우저 스크립트.

Python 문자열 안에 두면 편집기의 문법 강조·검사를 받지 못하므로 파일로 둔다. 몇 파일은 자리표시자를 쓴다.
  %TTS% : tts.js (듣기)    %FIT% : fit.js (폰 폭에 맞추기)    %MIN% : 줄일 수 있는 최소 배율
  image.css의 %W·%BG·%FG·%CHIP·%CHIPLINE·%ACCENT : 이미지 폭과 색
tests/test_assets.py가 자리표시자를 채운 결과를 Node로 문법 검사한다.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

DIR = Path(__file__).resolve().parent


@cache
def read(name: str) -> str:
    return (DIR / name).read_text(encoding="utf-8")
