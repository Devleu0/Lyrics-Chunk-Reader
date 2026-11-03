# 가사 직독직해 번역 툴

일본어·중국어·영어 가사를 **의미 단위로 끊어 한국어로 직역**하는 언어 학습용 로컬 웹 툴입니다.
로컬 LLM(Ollama)을 기본으로 쓰고, 필요하면 무료 API(Gemini, Groq 등)로 바꿔 쓸 수 있습니다.

## 보기 방식

한 번 번역하면 두 방식을 버튼으로 바로 전환합니다(재번역 없음).

| 원문 어순 (끊어읽기) | 한국어 어순 (직역) |
|---|---|
| `I've been waiting / for you / all night`<br>`나는 기다려 왔어 / 너를 / 밤새` | `I've been waiting for you all night`<br>`→ 나는 밤새 너를 기다려 왔어` |

결과는 Markdown(복습용)과 JSON(원본 데이터)으로 내보낼 수 있습니다.

## 설치

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # 필요한 값만 채우기
python app.py           # http://127.0.0.1:7860
```

### 엔진 1 — Ollama (로컬, 기본값, 추천)

1. https://ollama.com 에서 설치
2. 모델 받기: `ollama pull qwen3:8b`
   - 중국어·일본어에 강한 Qwen 계열을 권장합니다. VRAM/RAM이 부족하면 `qwen3:4b`, 여유가 있으면 `qwen3:14b`·`gemma3:12b`
3. 가사가 PC 밖으로 나가지 않고, 거부도 거의 없습니다.

### 엔진 2 — Gemini 무료 API

[Google AI Studio](https://aistudio.google.com)에서 키를 발급받아 `.env`의 `GEMINI_API_KEY`에 넣거나 화면에서 입력합니다.
저작물 재현 필터(RECITATION)에 걸리면 툴이 자동으로 줄 단위로 쪼개 다시 요청합니다.

### 엔진 3 — OpenAI 호환 API

Groq, OpenRouter, LM Studio 등 `/chat/completions`를 지원하는 서비스면 됩니다. `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`을 설정하세요.

> 무료 API의 사용량 한도와 모델 이름은 수시로 바뀝니다. 오류가 나면 각 서비스의 최신 모델명을 확인하세요.

## 거부·실패를 줄이는 장치

- 프롬프트를 "번역"이 아닌 **학습용 문법 주석** 작업으로 정의하고, 원문 재작성은 금지합니다.
- 기본 8줄씩 보내고, 실패하거나 거부된 줄만 **1줄 단위로 재시도**합니다(작은 단위가 필터를 덜 탑니다).
- 조각(chunks)을 이었을 때 원문과 80% 이상 일치하지 않으면 버리고 재시도합니다(환각 방지).
- 반복되는 후렴은 한 번만 번역해 재사용합니다.
- 그래도 실패한 줄은 ⚠ 표시와 이유를 보여줍니다. 엔진 설정에서 "한 번에 보낼 줄 수"를 줄이거나 엔진을 바꿔 보세요.

## 구조

```
app.py                  Gradio 웹 UI
lyrics_tool/
  backends.py           Ollama / Gemini / OpenAI 호환 엔진
  core.py               프롬프트, 배치·재시도, JSON 파싱·검증
  render.py             두 보기 방식의 HTML·Markdown 렌더링
tests/test_core.py      가짜 엔진 기반 테스트 (python -m pytest)
docs/learning-features-report.md   학습 편의 기능 정리 보고서
```

## 참고

입력한 가사는 개인 학습용으로만 사용하세요. 번역 결과를 공개 배포할 때는 원저작물의 권리를 확인해야 합니다.
