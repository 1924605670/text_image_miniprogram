import base64

import httpx
import pytest

from app.schemas import GenerationRequest
from app.services.image_client import (
    ImageClient,
    ImageProviderError,
    _response_error_message,
    is_retryable_status,
    normalize_provider_error_message,
)


def test_retryable_status_codes() -> None:
    assert is_retryable_status(408)
    assert is_retryable_status(429)
    assert is_retryable_status(500)
    assert not is_retryable_status(400)
    assert not is_retryable_status(401)


def test_html_504_error_is_sanitized() -> None:
    response = httpx.Response(
        504,
        text=(
            "<html><head><title>504 Gateway Time-out</title></head>"
            "<body><center><h1>504 Gateway Time-out</h1></center></body></html>"
        ),
    )

    message = _response_error_message(response)

    assert message.startswith("HTTP 504")
    assert "<html>" not in message
    assert "上游网关超时" in message


def test_stored_raw_504_error_is_sanitized() -> None:
    message = normalize_provider_error_message("HTTP 504: <html>504 Gateway Time-out</html>")

    assert message is not None
    assert "<html>" not in message
    assert "上游网关超时" in message


class DummySettings:
    api_key = "test-key"
    generation_url = "https://example.test/v1/images/generations"
    edit_url = "https://example.test/v1/images/edits"
    backup_api_key = ""
    backup_generation_url = ""
    backup_edit_url = ""
    backup_has_api_key = False
    has_api_key = True
    model = "gpt-image-2"
    retry_attempts = 5
    retry_base_delay_seconds = 0.01
    request_timeout_seconds = 30.0
    use_streaming = False
    partial_images = 0


async def test_generate_retries_retryable_api_errors_five_times(monkeypatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"error": {"message": "temporarily unavailable"}})

    async def no_sleep(attempt: int) -> None:
        return None

    original_async_client = httpx.AsyncClient
    image_client = ImageClient(DummySettings())
    monkeypatch.setattr(image_client, "_sleep_before_retry", no_sleep)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_async_client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ImageProviderError) as exc_info:
        await image_client.generate(GenerationRequest(prompt="test prompt"), "test prompt")

    assert calls == 5
    assert len(exc_info.value.attempt_log) == 5
    assert exc_info.value.attempt_log[-1].retryable is False


async def test_generate_returns_after_transient_failure(monkeypatch) -> None:
    image_bytes = b"\x89PNG\r\n\x1a\nfake"
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("temporary network issue", request=request)
        return httpx.Response(200, json={"data": [{"b64_json": image_b64}]})

    async def no_sleep(attempt: int) -> None:
        return None

    original_async_client = httpx.AsyncClient
    image_client = ImageClient(DummySettings())
    monkeypatch.setattr(image_client, "_sleep_before_retry", no_sleep)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_async_client(transport=httpx.MockTransport(handler)),
    )
    result = await image_client.generate(GenerationRequest(prompt="test prompt"), "test prompt")

    assert calls == 2
    assert result.attempts == 2
    assert len(result.attempt_log) == 2
    assert result.images[0].data == image_bytes


class BackupSettings(DummySettings):
    backup_api_key = "backup-key"
    backup_generation_url = "https://backup.example.test/v1/images/generations"
    backup_has_api_key = True
    retry_attempts = 4


async def test_generate_switches_to_backup_after_first_primary_error(monkeypatch) -> None:
    image_bytes = b"\x89PNG\r\n\x1a\nbackup"
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    seen_urls = []
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        seen_auth.append(request.headers.get("authorization"))
        if request.url.host == "example.test":
            return httpx.Response(400, json={"error": {"message": "primary failed"}})
        return httpx.Response(200, json={"data": [{"b64_json": image_b64}]})

    async def no_sleep(attempt: int) -> None:
        return None

    original_async_client = httpx.AsyncClient
    image_client = ImageClient(BackupSettings())
    monkeypatch.setattr(image_client, "_sleep_before_retry", no_sleep)
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_async_client(transport=httpx.MockTransport(handler)),
    )

    result = await image_client.generate(GenerationRequest(prompt="test prompt"), "test prompt")

    assert seen_urls == [
        "https://example.test/v1/images/generations",
        "https://backup.example.test/v1/images/generations",
    ]
    assert seen_auth == ["Bearer test-key", "Bearer backup-key"]
    assert result.attempts == 2
    assert result.images[0].data == image_bytes
    assert "backup" in result.attempt_log[-1].message


async def test_streaming_completed_event_extracts_image() -> None:
    image_bytes = b"\x89PNG\r\n\x1a\nfinal"
    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/images/generations"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                "event: image_generation.partial_image\n"
                f"data: {{\"type\":\"image_generation.partial_image\",\"b64_json\":\"{image_b64}\"}}\n\n"
                "event: image_generation.completed\n"
                f"data: {{\"type\":\"image_generation.completed\",\"b64_json\":\"{image_b64}\"}}\n\n"
            ),
        )

    image_client = ImageClient(DummySettings())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await image_client._request_stream(
            http_client,
            image_client._providers()[0],
            {"model": "gpt-image-2"},
            "png",
        )

    assert result.transport == "stream"
    assert len(result.images) == 1
    assert result.images[0].data == image_bytes


async def test_streaming_partial_data_list_is_ignored() -> None:
    partial_bytes = b"\x89PNG\r\n\x1a\npartial"
    final_bytes = b"\x89PNG\r\n\x1a\nfinal"
    partial_b64 = base64.b64encode(partial_bytes).decode("ascii")
    final_b64 = base64.b64encode(final_bytes).decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/images/generations"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                "event: image_generation.partial_image\n"
                f"data: {{\"type\":\"image_generation.partial_image\",\"data\":[{{\"b64_json\":\"{partial_b64}\"}}]}}\n\n"
                "event: image_generation.completed\n"
                f"data: {{\"type\":\"image_generation.completed\",\"data\":[{{\"b64_json\":\"{final_b64}\"}}]}}\n\n"
            ),
        )

    image_client = ImageClient(DummySettings())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await image_client._request_stream(
            http_client,
            image_client._providers()[0],
            {"model": "gpt-image-2"},
            "png",
        )

    assert len(result.images) == 1
    assert result.images[0].data == final_bytes
