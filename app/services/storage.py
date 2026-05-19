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
                    parent_job_id TEXT,
                    user_id TEXT
                )
                """
            )
            _ensure_column(connection, "jobs", "user_id", "TEXT")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    quota_total INTEGER NOT NULL DEFAULT 10,
                    quota_used INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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
        user_id: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, status, prompt, final_prompt, request_json, image_assets_json,
                    error, attempts, attempt_log_json, model, api_base_url,
                    created_at, updated_at, duration_ms, parent_job_id, user_id
                )
                VALUES (?, 'pending', ?, ?, ?, '[]', NULL, 0, '[]', ?, ?, ?, ?, NULL, ?, ?)
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
                    user_id,
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

    def list_jobs_by_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM jobs WHERE user_id = ?"
        values: list[Any] = [user_id]
        if status:
            sql += " AND status = ?"
            values.append(status)
        sql += " ORDER BY datetime(created_at) DESC LIMIT ?"
        values.append(limit)
        with self._lock, self._connect() as connection:
            rows = connection.execute(sql, values).fetchall()
        return [_row_to_dict(row) for row in rows]

    def ensure_user(self, user_id: str) -> dict[str, Any]:
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users (id, quota_total, quota_used, note, created_at, updated_at)
                VALUES (?, 10, 0, '', ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (user_id, now, now),
            )
        return self.get_user(user_id)

    def get_user(self, user_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise KeyError(user_id)
        return _user_row_to_dict(row)

    def list_users(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    u.*,
                    COUNT(j.id) AS job_count,
                    SUM(CASE WHEN j.status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded_count,
                    SUM(CASE WHEN j.status = 'failed' THEN 1 ELSE 0 END) AS failed_count
                FROM users u
                LEFT JOIN jobs j ON j.user_id = u.id
                GROUP BY u.id
                ORDER BY datetime(u.updated_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_user_row_to_dict(row) for row in rows]

    def consume_user_quota(self, user_id: str) -> dict[str, Any]:
        self.ensure_user(user_id)
        now = _now()
        with self._lock, self._connect() as connection:
            user = connection.execute(
                "SELECT quota_total, quota_used FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if user is None:
                raise KeyError(user_id)
            if int(user["quota_used"]) >= int(user["quota_total"]):
                raise QuotaExceededError(user_id)
            connection.execute(
                "UPDATE users SET quota_used = quota_used + 1, updated_at = ? WHERE id = ?",
                (now, user_id),
            )
        return self.get_user(user_id)

    def refund_user_quota(self, user_id: str | None) -> dict[str, Any] | None:
        if not user_id:
            return None
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE users
                SET quota_used = CASE WHEN quota_used > 0 THEN quota_used - 1 ELSE 0 END,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, user_id),
            )
        return self.get_user(user_id)

    def update_user_quota(
        self,
        user_id: str,
        *,
        quota_total: int | None = None,
        quota_used: int | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_user(user_id)
        fields: dict[str, Any] = {"updated_at": _now()}
        if quota_total is not None:
            fields["quota_total"] = max(0, int(quota_total))
        if quota_used is not None:
            fields["quota_used"] = max(0, int(quota_used))
        if note is not None:
            fields["note"] = note

        assignments = []
        values: list[Any] = []
        for key, value in fields.items():
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(user_id)

        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE users SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
            connection.execute(
                "UPDATE users SET quota_used = quota_total WHERE id = ? AND quota_used > quota_total",
                (user_id,),
            )
        return self.get_user(user_id)

    def user_stats(self, user_id: str) -> dict[str, Any]:
        self.ensure_user(user_id)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    u.*,
                    COUNT(j.id) AS job_count,
                    SUM(CASE WHEN j.status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded_count,
                    SUM(CASE WHEN j.status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                    SUM(CASE WHEN j.status IN ('pending', 'running') THEN 1 ELSE 0 END) AS active_count
                FROM users u
                LEFT JOIN jobs j ON j.user_id = u.id
                WHERE u.id = ?
                GROUP BY u.id
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            raise KeyError(user_id)
        return _user_row_to_dict(row)

    def admin_stats(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            users = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_users,
                    COALESCE(SUM(quota_total), 0) AS quota_total_sum,
                    COALESCE(SUM(quota_used), 0) AS quota_used_sum
                FROM users
                """
            ).fetchone()
            jobs = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_jobs,
                    SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded_jobs,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_jobs,
                    SUM(CASE WHEN status IN ('pending', 'running') THEN 1 ELSE 0 END) AS active_jobs
                FROM jobs
                """
            ).fetchone()
        return {
            "total_users": int(users["total_users"] or 0),
            "quota_total_sum": int(users["quota_total_sum"] or 0),
            "quota_used_sum": int(users["quota_used_sum"] or 0),
            "total_jobs": int(jobs["total_jobs"] or 0),
            "succeeded_jobs": int(jobs["succeeded_jobs"] or 0),
            "failed_jobs": int(jobs["failed_jobs"] or 0),
            "active_jobs": int(jobs["active_jobs"] or 0),
        }


class QuotaExceededError(RuntimeError):
    def __init__(self, user_id: str) -> None:
        super().__init__(f"user quota exceeded: {user_id}")
        self.user_id = user_id


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    record["request"] = json.loads(record.pop("request_json") or "{}")
    record["image_assets"] = json.loads(record.pop("image_assets_json") or "[]")
    record["attempt_log"] = json.loads(record.pop("attempt_log_json") or "[]")
    return record


def _user_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    total = int(record.get("quota_total") or 0)
    used = int(record.get("quota_used") or 0)
    record["quota_total"] = total
    record["quota_used"] = used
    record["quota_remaining"] = max(0, total - used)
    for key in ("job_count", "succeeded_count", "failed_count", "active_count"):
        if key in record:
            record[key] = int(record.get(key) or 0)
    return record


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
