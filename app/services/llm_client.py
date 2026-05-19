from __future__ import annotations

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

        timeout = httpx.Timeout(min(self.settings.request_timeout_seconds, 120.0), connect=20.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(self.settings.chat_completions_url, json=payload, headers=self._headers())
            if resp.status_code >= 400:
                raise PromptOptimizeError(_response_error_message(resp))
            data = resp.json()

        content = _extract_content(data)
        if not content:
            raise PromptOptimizeError("llm optimize returned empty content")
        return OptimizeResult(optimized_prompt=content)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, req: PromptOptimizeRequest) -> dict[str, Any]:
        return {
            "model": self.settings.llm_model,
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
        if isinstance(content, str):
            return content.strip()
    return ""


def _response_error_message(response: httpx.Response) -> str:
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
    return f"llm optimize failed: HTTP {response.status_code}: {body or response.reason_phrase}"
