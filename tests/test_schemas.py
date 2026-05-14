import pytest
from pydantic import ValidationError

from app.schemas import GenerationRequest


def test_size_accepts_gpt_image_2_supported_resolution() -> None:
    request = GenerationRequest(prompt="test prompt", size="2048x1152")

    assert request.size == "2048x1152"


def test_size_rejects_non_multiple_of_16() -> None:
    with pytest.raises(ValidationError):
        GenerationRequest(prompt="test prompt", size="1000x1000")

