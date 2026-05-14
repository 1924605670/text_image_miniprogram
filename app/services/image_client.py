from __future__ import annotations

import asyncio
import base64
import binascii
import json
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import Settings
from app.schemas import AttemptLog, GenerationRequest


RETRYABLE_STATUS_CODES = {408, 409, 425, 429}


def is_retryable_status(status_code: int) -> bool:
    return status_code in RETRYABLE_STATUS_CODES or status_code >= 500


@dataclass
class GeneratedImage:
    data: bytes
    extension: str
    revised_prompt: str | None = None


@dataclass
class GenerateResult:
    images: list[GeneratedImage]
    attempts: int
    attempt_log: list[AttemptLog] = field(default_factory=list)
    duration_ms: int = 0
    raw_usage: dict[str, Any] | None = None


@dataclass
class RequestOnceResult:
    images: list[GeneratedImage]
    usage: dict[str, Any] | None = None
    transport: str = "json"


@dataclass(frozen=True)
class ImageProvider:
    name: str
    generation_url: str
    api_key: str


class ImageProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        attempt_log: list[AttemptLog] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.attempt_log = attempt_log or []


class ImageClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def generate(self, request: GenerationRequest, final_prompt: str) -> GenerateResult:
        if not self.settings.has_api_key:
            raise ImageProviderError("IMAGE_API_KEY is missing")

        payload = self._payload(request, final_prompt)
        attempt_log: list[AttemptLog] = []
        started = time.perf_counter()
        timeout = httpx.Timeout(self.settings.request_timeout_seconds, connect=30.0)
        providers = self._providers()
        use_backup = False

        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(1, self.settings.retry_attempts + 1):
                provider = providers[1] if use_backup and len(providers) > 1 else providers[0]
                attempt_started = time.perf_counter()
                try:
                    once = await self._request_once(
                        client,
                        provider,
                        payload,
                        request.output_format,
                    )
                except httpx.RequestError as exc:
                    duration_ms = _elapsed_ms(attempt_started)
                    retryable = attempt < self.settings.retry_attempts
                    if retryable and len(providers) > 1:
                        use_backup = True
                    attempt_log.append(
                        AttemptLog(
                            attempt=attempt,
                            retryable=retryable,
                            duration_ms=duration_ms,
                            message=(
                                f"{provider.name} network error: {exc.__class__.__name__}"
                                f"{'; next attempt uses backup provider' if retryable and use_backup else ''}"
                            ),
                        )
                    )
                    if retryable:
                        await self._sleep_before_retry(attempt)
                        continue
                    raise ImageProviderError(str(exc), attempt_log=attempt_log) from exc
                except ImageProviderError as exc:
                    duration_ms = _elapsed_ms(attempt_started)
                    can_failover = provider.name == "primary" and len(providers) > 1
                    retryable = attempt < self.settings.retry_attempts and (
                        can_failover
                        or exc.status_code is None
                        or is_retryable_status(exc.status_code)
                    )
                    if retryable and len(providers) > 1:
                        use_backup = True
                    attempt_log.append(
                        AttemptLog(
                            attempt=attempt,
                            status_code=exc.status_code,
                            retryable=retryable,
                            duration_ms=duration_ms,
                            message=(
                                f"{provider.name}: {exc}"
                                f"{'; next attempt uses backup provider' if retryable and use_backup else ''}"
                            ),
                        )
                    )
                    if retryable:
                        await self._sleep_before_retry(attempt)
                        continue
                    raise ImageProviderError(
                        str(exc),
                        status_code=exc.status_code,
                        attempt_log=attempt_log,
                    ) from exc

                duration_ms = _elapsed_ms(attempt_started)
                attempt_log.append(
                    AttemptLog(
                        attempt=attempt,
                        retryable=False,
                        duration_ms=duration_ms,
                        message=f"ok via {provider.name} {once.transport}",
                    )
                )

                return GenerateResult(
                    images=once.images,
                    attempts=attempt,
                    attempt_log=attempt_log,
                    duration_ms=_elapsed_ms(started),
                    raw_usage=once.usage,
                )

        raise ImageProviderError("image generation failed", attempt_log=attempt_log)

    async def _request_once(
        self,
        client: httpx.AsyncClient,
        provider: ImageProvider,
        payload: dict[str, Any],
        fallback_extension: str,
    ) -> RequestOnceResult:
        if not self.settings.use_streaming:
            return await self._request_json(client, provider, payload, fallback_extension)

        stream_payload = {
            **payload,
            "stream": True,
            "partial_images": max(0, min(self.settings.partial_images, 3)),
        }
        try:
            return await self._request_stream(client, provider, stream_payload, fallback_extension)
        except ImageProviderError as exc:
            if exc.status_code in {400, 404, 422} and _looks_like_streaming_unsupported(str(exc)):
                fallback = await self._request_json(client, provider, payload, fallback_extension)
                fallback.transport = f"{fallback.transport} after stream fallback"
                return fallback
            raise

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        provider: ImageProvider,
        payload: dict[str, Any],
        fallback_extension: str,
    ) -> RequestOnceResult:
        response = await client.post(
            provider.generation_url,
            headers=self._headers(provider),
            json=payload,
        )
        if response.status_code >= 400:
            raise ImageProviderError(
                _response_error_message(response),
                status_code=response.status_code,
            )

        payload_json = _safe_json(response)
        images = await self._extract_images(client, payload_json, fallback_extension)
        if not images:
            raise ImageProviderError("provider returned no images")
        return RequestOnceResult(
            images=images,
            usage=payload_json.get("usage") if isinstance(payload_json, dict) else None,
            transport="json",
        )

    async def _request_stream(
        self,
        client: httpx.AsyncClient,
        provider: ImageProvider,
        payload: dict[str, Any],
        fallback_extension: str,
    ) -> RequestOnceResult:
        async with client.stream(
            "POST",
            provider.generation_url,
            headers=self._headers(provider),
            json=payload,
        ) as response:
            if response.status_code >= 400:
                await response.aread()
                raise ImageProviderError(
                    _response_error_message(response),
                    status_code=response.status_code,
                )

            content_type = response.headers.get("content-type", "")
            if "text/event-stream" not in content_type:
                await response.aread()
                payload_json = _safe_json(response)
                images = await self._extract_images(client, payload_json, fallback_extension)
                if not images:
                    raise ImageProviderError("provider returned no images")
                return RequestOnceResult(
                    images=images,
                    usage=payload_json.get("usage") if isinstance(payload_json, dict) else None,
                    transport="json",
                )

            images: list[GeneratedImage] = []
            usage: dict[str, Any] | None = None

            async for event in _aiter_sse_events(response):
                data = event.get("data", "").strip()
                if not data or data == "[DONE]":
                    continue

                try:
                    event_json = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise ImageProviderError("provider returned invalid streaming JSON") from exc

                event_type = str(event_json.get("type") or event.get("event") or "")
                if "partial" in event_type:
                    continue

                if isinstance(event_json.get("usage"), dict):
                    usage = event_json["usage"]

                if isinstance(event_json.get("data"), list):
                    images.extend(
                        await self._extract_images(client, event_json, fallback_extension)
                    )
                    continue

                b64_json = event_json.get("b64_json") or event_json.get("result")
                if b64_json and ("completed" in event_type or not event_type):
                    raw = _decode_base64_image(str(b64_json))
                    images.append(
                        GeneratedImage(
                            data=raw,
                            extension=_detect_extension(raw) or fallback_extension,
                            revised_prompt=(
                                event_json.get("revised_prompt")
                                if isinstance(event_json.get("revised_prompt"), str)
                                else None
                            ),
                        )
                    )

            if not images:
                raise ImageProviderError("provider stream completed without an image")
            return RequestOnceResult(images=images, usage=usage, transport="stream")

    def _payload(self, request: GenerationRequest, final_prompt: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "prompt": final_prompt,
            "n": request.n,
            "size": request.size,
            "quality": request.quality,
            "output_format": request.output_format,
            "background": request.background,
        }
        if request.output_format in {"jpeg", "webp"} and request.output_compression is not None:
            payload["output_compression"] = request.output_compression
        return payload

    def _providers(self) -> list[ImageProvider]:
        providers = [
            ImageProvider(
                name="primary",
                generation_url=self.settings.generation_url,
                api_key=self.settings.api_key,
            )
        ]
        if self.settings.backup_has_api_key:
            providers.append(
                ImageProvider(
                    name="backup",
                    generation_url=self.settings.backup_generation_url,
                    api_key=self.settings.backup_api_key,
                )
            )
        return providers

    def _headers(self, provider: ImageProvider) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

    async def _extract_images(
        self,
        client: httpx.AsyncClient,
        response_json: dict[str, Any],
        fallback_extension: str,
    ) -> list[GeneratedImage]:
        data = response_json.get("data")
        if not isinstance(data, list):
            raise ImageProviderError("provider response missing data[]")

        images: list[GeneratedImage] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            revised_prompt = item.get("revised_prompt")
            if item.get("b64_json"):
                raw = _decode_base64_image(str(item["b64_json"]))
            elif item.get("url"):
                raw = await self._download_image(client, str(item["url"]))
            else:
                continue

            extension = _detect_extension(raw) or fallback_extension
            images.append(
                GeneratedImage(
                    data=raw,
                    extension=extension,
                    revised_prompt=revised_prompt if isinstance(revised_prompt, str) else None,
                )
            )
        return images

    async def _download_image(self, client: httpx.AsyncClient, url: str) -> bytes:
        response = await client.get(url)
        if response.status_code >= 400:
            raise ImageProviderError(
                f"failed to download provider image url: HTTP {response.status_code}"
            )
        return response.content

    async def _sleep_before_retry(self, attempt: int) -> None:
        base = self.settings.retry_base_delay_seconds
        delay = min(12.0, base * (2 ** (attempt - 1))) + random.uniform(0, base)
        await asyncio.sleep(delay)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        parsed = response.json()
    except ValueError as exc:
        raise ImageProviderError("provider returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ImageProviderError("provider returned a non-object JSON response")
    return parsed


async def _aiter_sse_events(response: httpx.Response) -> Any:
    event_name: str | None = None
    data_lines: list[str] = []

    async for raw_line in response.aiter_lines():
        line = raw_line.rstrip("\r")
        if not line:
            if event_name or data_lines:
                yield {"event": event_name, "data": "\n".join(data_lines)}
            event_name = None
            data_lines = []
            continue

        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    if event_name or data_lines:
        yield {"event": event_name, "data": "\n".join(data_lines)}


def _response_error_message(response: httpx.Response) -> str:
    try:
        parsed = response.json()
    except ValueError:
        return normalize_provider_error_message(
            response.text,
            status_code=response.status_code,
            reason=response.reason_phrase,
        )

    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return normalize_provider_error_message(
            str(error["message"]),
            status_code=response.status_code,
            reason=response.reason_phrase,
        )
    if isinstance(parsed, dict) and parsed.get("message"):
        return normalize_provider_error_message(
            str(parsed["message"]),
            status_code=response.status_code,
            reason=response.reason_phrase,
        )
    return normalize_provider_error_message(
        "",
        status_code=response.status_code,
        reason=response.reason_phrase,
    )


def normalize_provider_error_message(
    message: str | None,
    *,
    status_code: int | None = None,
    reason: str | None = None,
) -> str | None:
    if message is None:
        return None

    body = _strip_html(message).strip()
    status = status_code or _extract_status_code(body)

    if status == 504 or "Gateway Time-out" in body or "Gateway Timeout" in body:
        return (
            "HTTP 504: 上游网关超时，图片生成耗时超过代理等待时间。"
            "系统已启用流式生成和自动重试；如果仍失败，建议降低尺寸或质量后再试。"
        )

    if status:
        suffix = body or reason or "provider request failed"
        return f"HTTP {status}: {suffix}"

    return body or reason or "provider request failed"


def _strip_html(value: str) -> str:
    compact = re.sub(r"\s+", " ", value or "").strip()
    if "<" not in compact or ">" not in compact:
        return compact
    text = re.sub(r"<[^>]+>", " ", compact)
    return re.sub(r"\s+", " ", text).strip()


def _extract_status_code(value: str) -> int | None:
    match = re.search(r"\bHTTP\s+(\d{3})\b", value, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(4\d{2}|5\d{2})\b", value)
    if match:
        return int(match.group(1))
    return None


def _looks_like_streaming_unsupported(message: str) -> bool:
    lower = message.lower()
    streaming_tokens = ("stream", "partial_images", "partial image", "event-stream")
    unsupported_tokens = ("unsupported", "not support", "unknown", "unrecognized", "invalid")
    return any(token in lower for token in streaming_tokens) and any(
        token in lower for token in unsupported_tokens
    )


def _decode_base64_image(value: str) -> bytes:
    if "," in value and value.lstrip().startswith("data:"):
        value = value.split(",", 1)[1]
    try:
        return base64.b64decode(value, validate=True)
    except binascii.Error as exc:
        raise ImageProviderError("provider returned invalid base64 image data") from exc


def _detect_extension(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return None
