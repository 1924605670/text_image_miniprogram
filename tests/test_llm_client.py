import httpx

from app.schemas import PromptOptimizeRequest
from app.services.llm_client import LLMClient, _response_error_message


def test_prompt_optimize_payload_uses_gpt_55_without_temperature() -> None:
    class DummySettings:
        llm_model = "gpt-5.5"
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
