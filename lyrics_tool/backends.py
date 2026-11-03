"""번역 엔진 백엔드.

모든 백엔드는 `chat(system, user) -> str` 하나만 구현한다.
- OllamaBackend   : 로컬 LLM (무료, 거부 거의 없음)
- GeminiBackend   : Google AI Studio 무료 티어
- OpenAICompatBackend : Groq / OpenRouter / LM Studio 등 OpenAI 호환 API

일시적인 오류(연결 끊김·시간 초과·429·5xx)는 `retries`번까지 기다렸다가 다시 요청한다.
서버가 기다릴 시간을 알려 주면(Retry-After, Gemini retryDelay) 그만큼, 아니면 2·4·8…초(최대 30초).
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
from dataclasses import dataclass, field

import requests

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_WAIT = 60  # 이보다 오래 기다리라고 하면(일일 한도 소진 등) 재시도하지 않는다


class BackendError(RuntimeError):
    """네트워크·인증·서버 오류."""


class RefusalError(BackendError):
    """모델 또는 API 안전 필터가 응답을 거부/차단함."""


@dataclass
class CheckResult:
    ok: bool
    message: str
    models: list[str] = field(default_factory=list)


@dataclass
class Backend:
    model: str
    timeout: int = 180
    temperature: float = 0.2
    retries: int = 3  # 일시적 오류 시 추가 시도 횟수

    name: str = field(default="base", init=False)

    def chat(self, system: str, user: str) -> str:  # pragma: no cover - 인터페이스
        raise NotImplementedError

    def _post(self, url: str, **kwargs) -> dict:
        for attempt in range(self.retries + 1):
            last = attempt == self.retries
            try:
                resp = requests.post(url, timeout=self.timeout, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as e:
                if isinstance(e, requests.Timeout):
                    msg = f"{self.name} 응답 시간 초과 ({self.timeout}s)"
                else:
                    msg = f"{self.name} 서버에 연결할 수 없습니다: {url}"
                if last:
                    raise BackendError(msg + _tries(attempt)) from e
                self._wait(attempt, None, msg)
                continue
            if resp.status_code < 400:
                return resp.json()
            msg = f"{self.name} 오류 {resp.status_code}: {_error_detail(resp)}"
            hint = _retry_after(resp)
            if resp.status_code not in RETRY_STATUS or last or (hint or 0) > MAX_WAIT:
                raise BackendError(msg + _tries(attempt))
            self._wait(attempt, hint, msg)
        raise AssertionError("unreachable")  # pragma: no cover

    def _wait(self, attempt: int, hint: float | None, reason: str) -> None:
        delay = hint if hint is not None else min(2 * 2**attempt, 30) + random.uniform(0, 1)
        log.warning("%s — %.0f초 후 다시 시도 (%d/%d)", reason.splitlines()[0], delay, attempt + 1, self.retries)
        time.sleep(delay)

    def _get(self, url: str, **kwargs) -> dict:
        try:
            resp = requests.get(url, timeout=10, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as e:
            raise BackendError(f"{self.name} 서버에 연결할 수 없습니다: {url}") from e
        if resp.status_code in (401, 403):
            raise BackendError(f"{self.name} 인증 실패 ({resp.status_code}) — API 키를 확인하세요.")
        if resp.status_code >= 400:
            raise BackendError(f"{self.name} 오류 {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def fetch_models(self) -> list[str]:  # pragma: no cover - 인터페이스
        raise NotImplementedError

    def check(self) -> CheckResult:
        """서버 연결·인증과 선택한 모델이 있는지 확인한다(번역 호출은 하지 않음)."""
        try:
            models = self.fetch_models()
        except BackendError as e:
            return CheckResult(False, str(e))
        if self.model and not _has_model(models, self.model):
            hint = f" — 터미널에서 `ollama pull {self.model}`" if self.name == "Ollama" else ""
            return CheckResult(False, f"연결됨. 하지만 모델 `{self.model}`을 찾을 수 없습니다{hint}.", models)
        return CheckResult(True, f"{self.name} 연결됨 · 모델 `{self.model}` 사용 가능", models)


def _tries(attempt: int) -> str:
    return f" ({attempt + 1}회 시도)" if attempt else ""


def _error_detail(resp: requests.Response) -> str:
    """오류 본문에서 사람이 읽을 메시지만 꺼낸다 (Gemini·OpenAI 형식: {"error": {"message": ...}})."""
    try:
        err = resp.json().get("error")
        msg = err.get("message") if isinstance(err, dict) else err
        if isinstance(msg, str) and msg:
            return msg[:300]
    except (ValueError, AttributeError):
        pass
    return resp.text[:300]


def _retry_after(resp: requests.Response) -> float | None:
    """서버가 알려 준 대기 시간(초). Retry-After 헤더 또는 Gemini 오류 본문의 retryDelay("21s")."""
    header = resp.headers.get("Retry-After", "")
    if header.strip().isdigit():
        return float(header)
    m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', resp.text)
    return float(m.group(1)) if m else None


def _has_model(models: list[str], model: str) -> bool:
    if not models:  # 목록을 주지 않는 서버는 통과
        return True
    names = set(models) | {m.removesuffix(":latest") for m in models}
    return model in names or model.removesuffix(":latest") in names


@dataclass
class OllamaBackend(Backend):
    host: str = "http://localhost:11434"
    name: str = field(default="Ollama", init=False)

    def chat(self, system: str, user: str) -> str:
        data = self._post(
            f"{self.host.rstrip('/')}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "format": "json",
                "stream": False,
                "think": False,  # qwen3 등 사고 모드 모델의 장황한 출력 방지
                "options": {"temperature": self.temperature, "num_ctx": 8192},
            },
        )
        return data.get("message", {}).get("content", "")

    def fetch_models(self) -> list[str]:
        data = self._get(f"{self.host.rstrip('/')}/api/tags")
        return [m["name"] for m in data.get("models", [])]

    def list_models(self) -> list[str]:
        try:
            return self.fetch_models()
        except BackendError:
            return []


@dataclass
class GeminiBackend(Backend):
    api_key: str = ""
    name: str = field(default="Gemini", init=False)

    def chat(self, system: str, user: str) -> str:
        if not self.api_key:
            raise BackendError("Gemini API 키가 없습니다 (GEMINI_API_KEY).")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        safety = [
            {"category": c, "threshold": "BLOCK_NONE"}
            for c in (
                "HARM_CATEGORY_HARASSMENT",
                "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "HARM_CATEGORY_DANGEROUS_CONTENT",
            )
        ]
        data = self._post(
            url,
            headers={"x-goog-api-key": self.api_key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "safetySettings": safety,
                "generationConfig": {
                    "temperature": self.temperature,
                    "responseMimeType": "application/json",
                },
            },
        )
        if data.get("promptFeedback", {}).get("blockReason"):
            raise RefusalError(f"Gemini 입력 차단: {data['promptFeedback']['blockReason']}")
        cands = data.get("candidates") or []
        if not cands:
            raise RefusalError("Gemini 응답 후보가 비어 있습니다.")
        reason = cands[0].get("finishReason", "")
        parts = cands[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        # RECITATION = 저작물 재현 필터. 줄을 잘게 나눠 재시도하면 통과되는 경우가 많다.
        if reason in ("RECITATION", "SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT") and not text:
            raise RefusalError(f"Gemini 응답 차단: {reason}")
        return text

    def fetch_models(self) -> list[str]:
        if not self.api_key:
            raise BackendError("Gemini API 키가 없습니다 (GEMINI_API_KEY).")
        data = self._get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": self.api_key},
            params={"pageSize": 200},
        )
        return [
            m["name"].removeprefix("models/")
            for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]


@dataclass
class OpenAICompatBackend(Backend):
    base_url: str = "https://api.groq.com/openai/v1"
    api_key: str = ""
    name: str = field(default="OpenAI 호환", init=False)

    def chat(self, system: str, user: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = self._post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": self.temperature,
                "response_format": {"type": "json_object"},
            },
        )
        choice = (data.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "content_filter":
            raise RefusalError("API 콘텐츠 필터에 의해 차단됨")
        return choice.get("message", {}).get("content") or ""

    def fetch_models(self) -> list[str]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = self._get(f"{self.base_url.rstrip('/')}/models", headers=headers)
        return sorted(m.get("id", "") for m in data.get("data", []) if m.get("id"))


BACKENDS = {"ollama": "Ollama (로컬)", "gemini": "Gemini (무료 API)", "openai": "OpenAI 호환 API"}


GEMINI_DEFAULT_MODEL = "gemini-3.6-flash"


def make_backend(kind: str, model: str = "", api_key: str = "", base_url: str = "", retries: int = 3) -> Backend:
    """UI/환경변수 값으로 백엔드를 만든다. 빈 값은 환경변수, 그것도 비었으면 기본값을 쓴다."""

    def env(key: str, default: str = "") -> str:
        return os.environ.get(key, "").strip() or default  # .env의 `KEY=` 처럼 빈 값도 기본값으로

    retries = max(0, int(retries))
    if kind == "ollama":
        return OllamaBackend(
            model=model or env("OLLAMA_MODEL", "qwen3:8b"),
            host=base_url or env("OLLAMA_HOST", "http://localhost:11434"),
            retries=retries,
        )
    if kind == "gemini":
        return GeminiBackend(
            model=model or env("GEMINI_MODEL", GEMINI_DEFAULT_MODEL),
            api_key=api_key or env("GEMINI_API_KEY"),
            retries=retries,
        )
    if kind == "openai":
        return OpenAICompatBackend(
            model=model or env("OPENAI_MODEL", "llama-3.3-70b-versatile"),
            base_url=base_url or env("OPENAI_BASE_URL", "https://api.groq.com/openai/v1"),
            api_key=api_key or env("OPENAI_API_KEY"),
            retries=retries,
        )
    raise ValueError(f"알 수 없는 백엔드: {kind}")
