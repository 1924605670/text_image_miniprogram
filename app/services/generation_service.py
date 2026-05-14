from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from app.config import Settings
from app.schemas import GenerationRequest
from app.services.image_client import GenerateResult, ImageClient, ImageProviderError
from app.services.prompt import compose_prompt
from app.services.storage import JobStore


class GenerationService:
    def __init__(self, *, settings: Settings, store: JobStore, client: ImageClient) -> None:
        self.settings = settings
        self.store = store
        self.client = client
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def create_generation(
        self,
        request: GenerationRequest,
        *,
        parent_job_id: str | None = None,
    ) -> dict:
        job_id = uuid.uuid4().hex
        final_prompt = compose_prompt(request)
        job = self.store.create_job(
            job_id=job_id,
            prompt=request.prompt,
            final_prompt=final_prompt,
            request=request.model_dump(),
            model=self.settings.model,
            api_base_url=self.settings.api_base_url,
            parent_job_id=parent_job_id,
        )
        task = asyncio.create_task(self._run_generation(job_id, request, final_prompt))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))
        return job

    def retry_generation(self, job_id: str) -> dict:
        source = self.store.get_job(job_id)
        if source["status"] in {"pending", "running"}:
            return source

        request = GenerationRequest.model_validate(source["request"])
        final_prompt = compose_prompt(request)
        self._delete_job_images(source)
        job = self.store.update_job(
            job_id,
            status="pending",
            final_prompt=final_prompt,
            image_assets_json="[]",
            error=None,
            attempts=0,
            attempt_log_json="[]",
            duration_ms=None,
        )
        task = asyncio.create_task(self._run_generation(job_id, request, final_prompt))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))
        return job

    async def _run_generation(
        self,
        job_id: str,
        request: GenerationRequest,
        final_prompt: str,
    ) -> None:
        self.store.update_job(job_id, status="running")
        try:
            result = await self.client.generate(request, final_prompt)
            assets = self._save_images(job_id, result)
            self.store.update_job(
                job_id,
                status="succeeded",
                image_assets_json=json.dumps(assets, ensure_ascii=False),
                error=None,
                attempts=result.attempts,
                attempt_log_json=json.dumps(
                    [item.model_dump() for item in result.attempt_log],
                    ensure_ascii=False,
                ),
                duration_ms=result.duration_ms,
            )
        except ImageProviderError as exc:
            self.store.update_job(
                job_id,
                status="failed",
                error=str(exc),
                attempts=len(exc.attempt_log),
                attempt_log_json=json.dumps(
                    [item.model_dump() for item in exc.attempt_log],
                    ensure_ascii=False,
                ),
            )
        except Exception as exc:
            self.store.update_job(job_id, status="failed", error=f"unexpected error: {exc}")

    def _save_images(self, job_id: str, result: GenerateResult) -> list[dict[str, str | None]]:
        self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        assets = []
        for index, image in enumerate(result.images, start=1):
            filename = _safe_filename(f"{job_id}-{index}.{image.extension}")
            path = self.settings.output_dir / filename
            path.write_bytes(image.data)
            assets.append({"filename": filename, "revised_prompt": image.revised_prompt})
        return assets

    def _delete_job_images(self, job: dict) -> None:
        for asset in job.get("image_assets", []):
            if not isinstance(asset, dict) or not asset.get("filename"):
                continue
            path = self.settings.output_dir / _safe_filename(str(asset["filename"]))
            if path.exists():
                path.unlink()


def _safe_filename(filename: str) -> str:
    return Path(filename).name.replace("/", "").replace("\\", "")
