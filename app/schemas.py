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
    reference_image: Optional[str] = Field(None, max_length=255)
    client_user_id: Optional[str] = Field(None, max_length=80)

    @field_validator("prompt", "negative_prompt", "reference_image", "client_user_id")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("client_user_id")
    @classmethod
    def validate_client_user_id(cls, value: str | None) -> str | None:
        if not value:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,80}", value):
            raise ValueError("client_user_id must be 6-80 chars of letters, numbers, _ or -")
        return value

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


class PromptOptimizeRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=4000)
    style_preset: str = "cinematic"
    size: str = "1024x1024"
    quality: Quality = "auto"
    output_format: OutputFormat = "png"


class PromptOptimizeResponse(BaseModel):
    optimized_prompt: str


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
    user_id: Optional[str] = None


class CreateGenerationResponse(BaseModel):
    job: JobOut


class ReferenceUploadBase64Request(BaseModel):
    image_base64: str = Field(..., min_length=1, max_length=30_000_000)
    filename: str = Field("reference", max_length=255)
    content_type: Optional[str] = Field(None, max_length=100)

    @field_validator("image_base64", "filename", "content_type")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class ReferenceFromGeneratedRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)

    @field_validator("filename")
    @classmethod
    def strip_filename(cls, value: str) -> str:
        return value.strip()


class ReferenceUploadResponse(BaseModel):
    filename: str
    url: str


class UserOut(BaseModel):
    id: str
    quota_total: int
    quota_used: int
    quota_remaining: int
    note: str = ""
    created_at: str
    updated_at: str
    job_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    active_count: int = 0


class AdminStatsOut(BaseModel):
    total_users: int
    quota_total_sum: int
    quota_used_sum: int
    total_jobs: int
    succeeded_jobs: int
    failed_jobs: int
    active_jobs: int


class UserQuotaUpdateRequest(BaseModel):
    quota_total: Optional[int] = Field(None, ge=0, le=100000)
    quota_used: Optional[int] = Field(None, ge=0, le=100000)
    note: Optional[str] = Field(None, max_length=200)

    @field_validator("note")
    @classmethod
    def strip_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class AuthLoginRequest(BaseModel):
    code: Optional[str] = Field(None, max_length=200)
    client_user_id: Optional[str] = Field(None, max_length=80)

    @field_validator("code", "client_user_id")
    @classmethod
    def strip_login_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class AuthLoginResponse(BaseModel):
    user_id: str
    login_type: str
    user: UserOut
