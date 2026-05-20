from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.local")


def _project_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    return int(raw)


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    return float(raw)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str, default: str = "") -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _generation_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/images/generations"):
        return base
    if base.endswith("/v1"):
        return f"{base}/images/generations"
    return f"{base}/v1/images/generations"


def _edit_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/images/edits"):
        return base
    if base.endswith("/images/generations"):
        return f"{base.removesuffix('/images/generations')}/images/edits"
    if base.endswith("/v1"):
        return f"{base}/images/edits"
    return f"{base}/v1/images/edits"


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _masked_key(api_key: str) -> str:
    if not api_key.strip():
        return "missing"
    return f"{api_key[:6]}...{api_key[-4:]}"


@dataclass(frozen=True)
class Settings:
    api_base_url: str = os.getenv("IMAGE_API_BASE_URL", "https://api1.hometodo.top").rstrip("/")
    api_key: str = os.getenv("IMAGE_API_KEY", "")
    backup_api_base_url: str = os.getenv("IMAGE_BACKUP_API_BASE_URL", "").rstrip("/")
    backup_api_key: str = os.getenv("IMAGE_BACKUP_API_KEY", "")
    model: str = os.getenv("IMAGE_MODEL", "gpt-image-2")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-5.5")
    llm_fallback_models: tuple[str, ...] = _csv_env(
        "LLM_FALLBACK_MODELS",
        "minimaxai/minimax-m2.7",
    )
    output_dir: Path = _project_path(os.getenv("IMAGE_OUTPUT_DIR", "generated"))
    reference_dir: Path = _project_path(os.getenv("IMAGE_REFERENCE_DIR", "references"))
    database_path: Path = _project_path(os.getenv("IMAGE_DATABASE_PATH", "data/app.db"))
    retry_attempts: int = _int_env("IMAGE_RETRY_ATTEMPTS", 5)
    retry_base_delay_seconds: float = _float_env("IMAGE_RETRY_BASE_DELAY_SECONDS", 1.2)
    request_timeout_seconds: float = _float_env("IMAGE_REQUEST_TIMEOUT_SECONDS", 600.0)
    use_streaming: bool = _bool_env("IMAGE_USE_STREAMING", False)
    partial_images: int = _int_env("IMAGE_PARTIAL_IMAGES", 2)
    image_base_url: str = os.getenv("IMAGE_PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    admin_token: str = os.getenv("ADMIN_TOKEN", "")
    wechat_app_id: str = os.getenv("WECHAT_APP_ID", "")
    wechat_app_secret: str = os.getenv("WECHAT_APP_SECRET", "")

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key.strip())

    @property
    def masked_api_key(self) -> str:
        return _masked_key(self.api_key)

    @property
    def backup_has_api_key(self) -> bool:
        return bool(self.backup_api_key.strip() and self.backup_api_base_url.strip())

    @property
    def backup_masked_api_key(self) -> str:
        return _masked_key(self.backup_api_key)

    @property
    def generation_url(self) -> str:
        return _generation_url(self.api_base_url)

    @property
    def backup_generation_url(self) -> str:
        return _generation_url(self.backup_api_base_url)

    @property
    def edit_url(self) -> str:
        return _edit_url(self.api_base_url)

    @property
    def backup_edit_url(self) -> str:
        return _edit_url(self.backup_api_base_url)

    @property
    def chat_completions_url(self) -> str:
        return _chat_completions_url(self.api_base_url)


settings = Settings()
settings.output_dir.mkdir(parents=True, exist_ok=True)
settings.reference_dir.mkdir(parents=True, exist_ok=True)
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
