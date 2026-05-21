import json

import httpx
import pytest

from app.schemas import PromptOptimizeRequest
from app.services.llm_client import (
    LLMClient,
    PromptOptimizeError,
    _response_error_message,
)


def test_prompt_optimize_payload_uses_gpt_55_without_temperature() -> None:
    class DummySettings:
        llm_model = "gpt-5.5"
        llm_fallback_models = ()
        api_key = "test-key"

    client = LLMClient(DummySettings())

    payload = client._payload(PromptOptimizeRequest(prompt="雨夜城市"))

    assert payload["model"] == "gpt-5.5"
    assert "temperature" not in payload
    assert "keep them out of the optimized prompt text" in payload["messages"][1]["content"]


def test_llm_error_message_includes_provider_body() -> None:
    response = httpx.Response(
        503,
        json={
            "error": {
                "message": "All credentials for model gpt-5.5 are cooling down",
            }
        },
    )

    message = _response_error_message(response)

    assert "HTTP 503" in message
    assert "gpt-5.5" in message


async def test_post_chat_raises_clean_error_on_non_json_success(monkeypatch) -> None:
    class DummySettings:
        api_key = "test-key"
        request_timeout_seconds = 30.0
        chat_completions_url = "https://example.test/v1/chat/completions"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="", request=request)

    original_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.services.llm_client.httpx.AsyncClient",
        lambda *args, **kwargs: original_async_client(
            *args,
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )

    client = LLMClient(DummySettings())
    with pytest.raises(PromptOptimizeError) as exc_info:
        await client._post_chat({}, "llm optimize failed", PromptOptimizeError)

    message = str(exc_info.value)
    assert "HTTP 200" in message
    assert "provider returned invalid JSON" in message
    assert "<empty response body>" in message


async def test_post_chat_raises_clean_error_on_timeout(monkeypatch) -> None:
    class DummySettings:
        api_key = "test-key"
        request_timeout_seconds = 30.0
        chat_completions_url = "https://example.test/v1/chat/completions"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow provider", request=request)

    original_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.services.llm_client.httpx.AsyncClient",
        lambda *args, **kwargs: original_async_client(
            *args,
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )

    client = LLMClient(DummySettings())
    with pytest.raises(PromptOptimizeError) as exc_info:
        await client._post_chat({}, "llm optimize failed", PromptOptimizeError)

    assert str(exc_info.value) == "llm optimize failed: provider request timed out"


async def test_post_chat_falls_back_after_empty_stream(monkeypatch) -> None:
    class DummySettings:
        api_key = "test-key"
        llm_model = "gpt-5.5"
        llm_fallback_models = ("minimaxai/minimax-m2.7",)
        request_timeout_seconds = 30.0
        chat_completions_url = "https://example.test/v1/chat/completions"

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        if payload["model"] == "gpt-5.5":
            return httpx.Response(
                200,
                text='data: {"choices":[]}\n\ndata: [DONE]\n\n',
                headers={"content-type": "text/event-stream"},
                request=request,
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "雨夜城市，电影感构图"}}]},
            request=request,
        )

    original_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.services.llm_client.httpx.AsyncClient",
        lambda *args, **kwargs: original_async_client(
            *args,
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )

    client = LLMClient(DummySettings())
    content = await client._post_chat_with_fallback(
        {"model": "gpt-5.5", "messages": []},
        "llm optimize failed",
        PromptOptimizeError,
    )

    assert content == "雨夜城市，电影感构图"
