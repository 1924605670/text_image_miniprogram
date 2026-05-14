from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


Quality = Literal["auto", "low", "medium", "high"]
OutputFormat = Literal["png", "jpeg", "webp"]
Background = Literal["auto", "opaque"]
JobStatus = Literal["pending", "running", "succeeded", "failed"]


class GenerationRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=4000)
    negative_prompt: str = Field("", max_length=1200)
    style_preset: str = "cinematic"
    size: str = "1024x1024"
    quality: Quality = "auto"
    output_format: OutputFormat = "png"
    output_compression: Optional[int] = Field(None, ge=0, le=100)
    background: Background = "auto"
    n: int = Field(1, ge=1, le=4)

    @field_validator("prompt", "negative_prompt")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("size")
    @classmethod
    def validate_size(cls, value: str) -> str:
        if value == "auto":
            return value

        match = re.fullmatch(r"(\d{2,4})x(\d{2,4})", value)
        if not match:
            raise ValueError("size must be auto or WIDTHxHEIGHT")

        width = int(match.group(1))
        height = int(match.group(2))
        long_edge = max(width, height)
        short_edge = min(width, height)
        pixels = width * height

        if long_edge > 3840:
            raise ValueError("maximum edge length is 3840px")
        if width % 16 != 0 or height % 16 != 0:
            raise ValueError("width and height must be multiples of 16")
        if long_edge / short_edge > 3:
            raise ValueError("long edge to short edge ratio must not exceed 3:1")
        if pixels < 655_360 or pixels > 8_294_400:
            raise ValueError("total pixels must be between 655360 and 8294400")

        return value


class StylePreset(BaseModel):
    id: str
    label: str
    prompt_suffix: str


class ImageAsset(BaseModel):
    filename: str
    url: str
    revised_prompt: Optional[str] = None


class AttemptLog(BaseModel):
    attempt: int
    status_code: Optional[int] = None
    retryable: bool
    duration_ms: int
    message: str


class JobOut(BaseModel):
    id: str
    status: JobStatus
    prompt: str
    final_prompt: str
    request: dict[str, Any]
    images: list[ImageAsset] = Field(default_factory=list)
    error: Optional[str] = None
    attempts: int = 0
    attempt_log: list[AttemptLog] = Field(default_factory=list)
    model: str
    api_base_url: str
    created_at: str
    updated_at: str
    duration_ms: Optional[int] = None
    parent_job_id: Optional[str] = None


class CreateGenerationResponse(BaseModel):
    job: JobOut
