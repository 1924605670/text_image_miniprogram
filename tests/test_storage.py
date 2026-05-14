from pathlib import Path

from app.services.storage import JobStore


def test_job_store_roundtrip(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "app.db")

    created = store.create_job(
        job_id="job-1",
        prompt="hello",
        final_prompt="hello final",
        request={"prompt": "hello", "n": 1},
        model="gpt-image-2",
        api_base_url="https://api.example.test",
    )
    updated = store.update_job("job-1", status="succeeded", attempts=1)

    assert created["status"] == "pending"
    assert updated["status"] == "succeeded"
    assert store.get_job("job-1")["request"]["prompt"] == "hello"
    assert len(store.list_jobs()) == 1

