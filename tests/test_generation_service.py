import asyncio
from pathlib import Path

from app.services.generation_service import GenerationService
from app.services.image_client import GenerateResult, GeneratedImage
from app.services.storage import JobStore


class DummySettings:
    model = "gpt-image-2"
    api_base_url = "https://api.example.test"

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir


class DummyClient:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request, final_prompt: str) -> GenerateResult:
        self.calls += 1
        return GenerateResult(
            images=[GeneratedImage(data=b"\x89PNG\r\n\x1a\nfinal", extension="png")],
            attempts=1,
            duration_ms=12,
        )


async def test_retry_updates_existing_job_instead_of_creating_record(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "app.db")
    client = DummyClient()
    service = GenerationService(
        settings=DummySettings(tmp_path / "generated"),
        store=store,
        client=client,
    )
    store.create_job(
        job_id="job-1",
        prompt="hello",
        final_prompt="hello",
        request={"prompt": "hello", "n": 1},
        model="gpt-image-2",
        api_base_url="https://api.example.test",
    )
    store.update_job("job-1", status="failed", error="old error")

    job = service.retry_generation("job-1")

    assert job["id"] == "job-1"
    assert len(store.list_jobs()) == 1
    assert store.get_job("job-1")["status"] == "pending"

    for _ in range(20):
        if store.get_job("job-1")["status"] == "succeeded":
            break
        await asyncio.sleep(0.01)

    updated = store.get_job("job-1")
    assert updated["status"] == "succeeded"
    assert updated["error"] is None
    assert updated["attempts"] == 1
    assert client.calls == 1
    assert (tmp_path / "generated" / "job-1-1.png").exists()


async def test_retry_does_not_start_duplicate_running_job(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "app.db")
    client = DummyClient()
    service = GenerationService(
        settings=DummySettings(tmp_path / "generated"),
        store=store,
        client=client,
    )
    store.create_job(
        job_id="job-1",
        prompt="hello",
        final_prompt="hello",
        request={"prompt": "hello", "n": 1},
        model="gpt-image-2",
        api_base_url="https://api.example.test",
    )
    store.update_job("job-1", status="running")

    job = service.retry_generation("job-1")

    assert job["id"] == "job-1"
    assert job["status"] == "running"
    assert client.calls == 0
    assert len(store.list_jobs()) == 1
