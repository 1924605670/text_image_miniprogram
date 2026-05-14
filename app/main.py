from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import PROJECT_ROOT, settings
from app.schemas import CreateGenerationResponse, GenerationRequest, ImageAsset, JobOut
from app.services.generation_service import GenerationService
from app.services.image_client import ImageClient, normalize_provider_error_message
from app.services.prompt import style_options
from app.services.storage import JobStore


STATIC_DIR = PROJECT_ROOT / "app" / "static"

app = FastAPI(title="Text Image Demo", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

store = JobStore(settings.database_path)
generation_service = GenerationService(
    settings=settings,
    store=store,
    client=ImageClient(settings),
)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": {
            "base_url": settings.api_base_url,
            "generation_url": settings.generation_url,
            "model": settings.model,
            "api_key": settings.masked_api_key,
            "has_api_key": settings.has_api_key,
            "backup_base_url": settings.backup_api_base_url,
            "backup_generation_url": (
                settings.backup_generation_url if settings.backup_api_base_url else ""
            ),
            "backup_api_key": settings.backup_masked_api_key,
            "backup_has_api_key": settings.backup_has_api_key,
        },
        "storage": {
            "database": str(settings.database_path),
            "output_dir": str(settings.output_dir),
        },
        "retry": {
            "attempts": settings.retry_attempts,
            "base_delay_seconds": settings.retry_base_delay_seconds,
            "timeout_seconds": settings.request_timeout_seconds,
            "streaming": settings.use_streaming,
            "partial_images": settings.partial_images,
        },
    }


@app.get("/api/options")
async def options() -> dict[str, Any]:
    return {
        "styles": style_options(),
        "sizes": [
            {"value": "1024x1024", "label": "1:1 1024"},
            {"value": "1536x1024", "label": "3:2 1536x1024"},
            {"value": "1024x1536", "label": "2:3 1024x1536"},
            {"value": "2048x2048", "label": "2K 1:1"},
            {"value": "2048x1152", "label": "2K 16:9"},
            {"value": "3840x2160", "label": "4K 16:9"},
            {"value": "2160x3840", "label": "4K 9:16"},
            {"value": "auto", "label": "自动"},
        ],
        "qualities": ["auto", "low", "medium", "high"],
        "formats": ["png", "jpeg", "webp"],
        "backgrounds": ["auto", "opaque"],
    }


@app.post("/api/generations", response_model=CreateGenerationResponse, status_code=202)
async def create_generation(request: GenerationRequest) -> CreateGenerationResponse:
    job = generation_service.create_generation(request)
    return CreateGenerationResponse(job=_job_out(job))


@app.get("/api/generations", response_model=list[JobOut])
async def list_generations(limit: int = 30) -> list[JobOut]:
    limit = max(1, min(limit, 100))
    return [_job_out(job) for job in store.list_jobs(limit=limit)]


@app.get("/api/generations/{job_id}", response_model=JobOut)
async def get_generation(job_id: str) -> JobOut:
    try:
        return _job_out(store.get_job(job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@app.post("/api/generations/{job_id}/retry", response_model=CreateGenerationResponse, status_code=202)
async def retry_generation(job_id: str) -> CreateGenerationResponse:
    try:
        job = generation_service.retry_generation(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    return CreateGenerationResponse(job=_job_out(job))


@app.get("/api/images/{filename}")
async def read_image(filename: str) -> FileResponse:
    clean_name = Path(filename).name
    if clean_name != filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    path = settings.output_dir / clean_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(path)


def _job_out(record: dict[str, Any]) -> JobOut:
    images = [
        ImageAsset(
            filename=asset["filename"],
            url=f"/api/images/{asset['filename']}",
            revised_prompt=asset.get("revised_prompt"),
        )
        for asset in record.get("image_assets", [])
    ]
    return JobOut(
        id=record["id"],
        status=record["status"],
        prompt=record["prompt"],
        final_prompt=record["final_prompt"],
        request=record["request"],
        images=images,
        error=normalize_provider_error_message(record.get("error")),
        attempts=record.get("attempts") or 0,
        attempt_log=_clean_attempt_log(record.get("attempt_log") or []),
        model=record["model"],
        api_base_url=record["api_base_url"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        duration_ms=record.get("duration_ms"),
        parent_job_id=record.get("parent_job_id"),
    )


def _clean_attempt_log(attempt_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for item in attempt_log:
        if not isinstance(item, dict):
            continue
        next_item = dict(item)
        next_item["message"] = normalize_provider_error_message(
            str(next_item.get("message") or ""),
            status_code=next_item.get("status_code"),
        )
        cleaned.append(next_item)
    return cleaned
