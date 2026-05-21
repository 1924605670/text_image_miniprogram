from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings
from app.schemas import PromptOptimizeRequest


class PromptOptimizeError(RuntimeError):
    pass


@dataclass
class OptimizeResult:
    optimized_prompt: str


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def optimize_prompt(self, req: PromptOptimizeRequest) -> OptimizeResult:
        if not self.settings.has_api_key:
            raise PromptOptimizeError("IMAGE_API_KEY is missing")

        payload = self._payload(req)

        content = await self._post_chat_with_fallback(
            payload,
            "llm optimize failed",
            PromptOptimizeError,
        )
        if not content:
            raise PromptOptimizeError("llm optimize returned empty content")
        return OptimizeResult(optimized_prompt=content)

    async def _post_chat_with_fallback(
        self,
        payload: dict[str, Any],
        error_prefix: str,
        error_cls: type[RuntimeError],
    ) -> str:
        failures: list[str] = []
        for model in _candidate_llm_models(self.settings):
            model_payload = {**payload, "model": model}
            try:
                content = await self._post_chat(model_payload, error_prefix, error_cls)
            except error_cls as exc:
                failures.append(f"{model}: {exc}")
                continue
            if content:
                return content
            failures.append(f"{model}: empty content")
        raise error_cls(_all_model_failures_message(error_prefix, failures))

    async def _post_chat(
        self,
        payload: dict[str, Any],
        error_prefix: str,
        error_cls: type[RuntimeError],
    ) -> str:
        timeout = httpx.Timeout(min(self.settings.request_timeout_seconds, 180.0), connect=20.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.post(
                    self.settings.chat_completions_url,
                    json=payload,
                    headers=self._headers(),
                )
            except httpx.TimeoutException as exc:
                raise error_cls(f"{error_prefix}: provider request timed out") from exc
            except httpx.HTTPError as exc:
                raise error_cls(f"{error_prefix}: provider request failed: {exc}") from exc
            if resp.status_code >= 400:
                raise error_cls(_response_error_message(resp, prefix=error_prefix))

        return _extract_response_content(resp, error_prefix, error_cls)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, req: PromptOptimizeRequest) -> dict[str, Any]:
        return {
            "model": self.settings.llm_model,
            "max_tokens": 600,
            "messages": [
                {"role": "system", "content": _system_instruction()},
                {"role": "user", "content": _user_brief(req)},
            ],
        }


def _system_instruction() -> str:
    return (
        "You are an expert GPT-Image-2 prompt engineer. "
        "Rewrite user input into a production-ready image prompt. "
        "Keep original intent, language, and key entities. "
        "Use a structured creative-brief style with concrete visual details.\n\n"
        "Output rules:\n"
        "1) Return plain prompt text only, no headings, no markdown, no quotes.\n"
        "2) Include: scene, subject, composition, lens/view, lighting, material/texture, mood, style cues, and quality constraints.\n"
        "3) If user requests text-in-image, preserve exact quoted text faithfully.\n"
        "4) Avoid contradictions and unsafe content.\n"
        "5) Do not mention output size, aspect ratio, file format, or literal quality setting; those are controlled by UI parameters.\n"
        "6) Keep within ~80-220 Chinese characters when user writes Chinese; otherwise ~60-180 English words."
    )


def _user_brief(req: PromptOptimizeRequest) -> str:
    return (
        f"User prompt: {req.prompt.strip()}\n"
        f"Style preset: {req.style_preset}\n"
        f"Target size: {req.size}\n"
        f"Quality: {req.quality}\n"
        f"Output format: {req.output_format}\n"
        "Use these UI parameters as context, but keep them out of the optimized prompt text."
    )


def _extract_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
    if isinstance(msg, dict):
        content = msg.get("content")
        parsed = _content_value(content)
        if parsed:
            return parsed
    return ""


def _extract_response_content(
    response: httpx.Response,
    error_prefix: str,
    error_cls: type[RuntimeError],
) -> str:
    content_type = response.headers.get("content-type", "")
    text = response.text
    if "text/event-stream" in content_type or text.lstrip().startswith("data:"):
        try:
            return _extract_stream_content(text)
        except ValueError as exc:
            raise error_cls(_response_invalid_json_message(response, prefix=error_prefix)) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise error_cls(_response_invalid_json_message(response, prefix=error_prefix)) from exc
    if not isinstance(data, dict):
        raise error_cls(f"{error_prefix}: provider returned non-object JSON")
    return _extract_content(data)


def _extract_stream_content(text: str) -> str:
    parts: list[str] = []
    for data in _iter_sse_data(text):
        data = data.strip()
        if not data or data == "[DONE]":
            continue
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ValueError("provider returned invalid streaming JSON") from exc
        if not isinstance(parsed, dict):
            continue
        top_level = _content_value(parsed.get("content") or parsed.get("output_text"))
        if top_level:
            parts.append(top_level)
        choices = parsed.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            for key in ("delta", "message"):
                node = choice.get(key)
                if not isinstance(node, dict):
                    continue
                content = _content_value(node.get("content"))
                if content:
                    parts.append(content)
            text_value = _content_value(choice.get("text"))
            if text_value:
                parts.append(text_value)
    return "".join(parts).strip()


def _iter_sse_data(text: str) -> list[str]:
    data_items: list[str] = []
    data_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            if data_lines:
                data_items.append("\n".join(data_lines))
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        data_items.append("\n".join(data_lines))
    return data_items


def _content_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "".join(parts).strip()


def _response_error_message(response: httpx.Response, *, prefix: str = "llm optimize failed") -> str:
    try:
        parsed = response.json()
    except ValueError:
        body = response.text.strip()
    else:
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(error, dict) and error.get("message"):
            body = str(error["message"]).strip()
        elif isinstance(parsed, dict) and parsed.get("message"):
            body = str(parsed["message"]).strip()
        else:
            body = ""
    return f"{prefix}: HTTP {response.status_code}: {body or response.reason_phrase}"


def _response_invalid_json_message(response: httpx.Response, *, prefix: str = "llm optimize failed") -> str:
    body = _response_text_snippet(response)
    return f"{prefix}: HTTP {response.status_code}: provider returned invalid JSON: {body}"


def _response_text_snippet(response: httpx.Response, max_length: int = 220) -> str:
    text = response.text.strip()
    if not text:
        return "<empty response body>"
    text = " ".join(text.split())
    if len(text) <= max_length:
        return text
    return f"{text[:max_length].rstrip()}..."


def _candidate_llm_models(settings: Settings) -> list[str]:
    configured = [settings.llm_model, *getattr(settings, "llm_fallback_models", ())]
    models: list[str] = []
    for model in configured:
        value = str(model).strip()
        if value and value not in models:
            models.append(value)
    return models


def _all_model_failures_message(error_prefix: str, failures: list[str]) -> str:
    if not failures:
        return f"{error_prefix}: no configured LLM model"
    details = "; ".join(_truncate_failure(item) for item in failures[:4])
    if len(failures) > 4:
        details = f"{details}; ..."
    return f"{error_prefix}: all configured LLM models failed: {details}"


def _truncate_failure(value: str, max_length: int = 180) -> str:
    compact = " ".join(value.split())
    if len(compact) <= max_length:
        return compact
    return f"{compact[:max_length].rstrip()}..."
