from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JobStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    final_prompt TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    image_assets_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    attempt_log_json TEXT NOT NULL DEFAULT '[]',
                    model TEXT NOT NULL,
                    api_base_url TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    duration_ms INTEGER,
                    parent_job_id TEXT
                )
                """
            )

    def create_job(
        self,
        *,
        job_id: str,
        prompt: str,
        final_prompt: str,
        request: dict[str, Any],
        model: str,
        api_base_url: str,
        parent_job_id: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, status, prompt, final_prompt, request_json, image_assets_json,
                    error, attempts, attempt_log_json, model, api_base_url,
                    created_at, updated_at, duration_ms, parent_job_id
                )
                VALUES (?, 'pending', ?, ?, ?, '[]', NULL, 0, '[]', ?, ?, ?, ?, NULL, ?)
                """,
                (
                    job_id,
                    prompt,
                    final_prompt,
                    json.dumps(request, ensure_ascii=False),
                    model,
                    api_base_url,
                    now,
                    now,
                    parent_job_id,
                ),
            )
        return self.get_job(job_id)

    def update_job(self, job_id: str, **fields: Any) -> dict[str, Any]:
        if not fields:
            return self.get_job(job_id)

        fields["updated_at"] = _now()
        allowed = {
            "status",
            "final_prompt",
            "image_assets_json",
            "error",
            "attempts",
            "attempt_log_json",
            "duration_ms",
            "updated_at",
        }
        assignments = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"cannot update field: {key}")
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(job_id)

        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return _row_to_dict(row)

    def list_jobs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY datetime(created_at) DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    record["request"] = json.loads(record.pop("request_json") or "{}")
    record["image_assets"] = json.loads(record.pop("image_assets_json") or "[]")
    record["attempt_log"] = json.loads(record.pop("attempt_log_json") or "[]")
    return record


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

