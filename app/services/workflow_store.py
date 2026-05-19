from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.workflow_schemas import DEFAULT_COMPLETED_RELEASE_CHECKLIST, DEFAULT_RELEASE_CHECKLIST


class WorkflowStore:
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
                CREATE TABLE IF NOT EXISTS workflow_requirements (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    background TEXT NOT NULL,
                    business_goal TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    acceptance_criteria TEXT NOT NULL,
                    expected_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_development_tasks (
                    id TEXT PRIMARY KEY,
                    requirement_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    developer TEXT NOT NULL,
                    status TEXT NOT NULL,
                    self_test_notes TEXT NOT NULL DEFAULT '',
                    commit_notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(requirement_id) REFERENCES workflow_requirements(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_test_tasks (
                    id TEXT PRIMARY KEY,
                    development_task_id TEXT NOT NULL,
                    requirement_id TEXT NOT NULL,
                    test_cases TEXT NOT NULL,
                    tester TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_notes TEXT NOT NULL DEFAULT '',
                    defect_notes TEXT NOT NULL DEFAULT '',
                    retest_notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(development_task_id) REFERENCES workflow_development_tasks(id),
                    FOREIGN KEY(requirement_id) REFERENCES workflow_requirements(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_release_tasks (
                    id TEXT PRIMARY KEY,
                    test_task_id TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    status TEXT NOT NULL,
                    server_deploy_result TEXT NOT NULL DEFAULT '',
                    mini_program_test_result TEXT NOT NULL DEFAULT '',
                    version TEXT NOT NULL DEFAULT '',
                    release_notes TEXT NOT NULL DEFAULT '',
                    rollback_notes TEXT NOT NULL DEFAULT '',
                    release_checklist TEXT NOT NULL DEFAULT '',
                    risk_notes TEXT NOT NULL DEFAULT '',
                    known_issues TEXT NOT NULL DEFAULT '',
                    test_version_url TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(test_task_id) REFERENCES workflow_test_tasks(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_acceptances (
                    id TEXT PRIMARY KEY,
                    release_task_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    blocker_notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(release_task_id) REFERENCES workflow_release_tasks(id)
                )
                """
            )
            self._ensure_column(connection, "workflow_release_tasks", "release_checklist", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "workflow_release_tasks", "risk_notes", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "workflow_release_tasks", "known_issues", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "workflow_release_tasks", "test_version_url", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "workflow_acceptances", "blocker_notes", "TEXT NOT NULL DEFAULT ''")
            connection.execute(
                """
                UPDATE workflow_release_tasks
                SET release_checklist = ?
                WHERE release_checklist = '' AND status = 'submitted_test_version'
                """,
                (DEFAULT_COMPLETED_RELEASE_CHECKLIST,),
            )
            connection.execute(
                """
                UPDATE workflow_release_tasks
                SET release_checklist = ?
                WHERE release_checklist = ''
                """,
                (DEFAULT_RELEASE_CHECKLIST,),
            )

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_requirement(self, data: dict[str, Any]) -> dict[str, Any]:
        record = {**data, "id": _id(), "status": "draft", "created_at": _now(), "updated_at": _now()}
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflow_requirements (
                    id, title, background, business_goal, priority, scope,
                    acceptance_criteria, expected_version, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _values(
                    record,
                    "id",
                    "title",
                    "background",
                    "business_goal",
                    "priority",
                    "scope",
                    "acceptance_criteria",
                    "expected_version",
                    "status",
                    "created_at",
                    "updated_at",
                ),
            )
        return self.get_requirement(record["id"])

    def list_requirements(self) -> list[dict[str, Any]]:
        return self._list("workflow_requirements")

    def get_requirement(self, record_id: str) -> dict[str, Any]:
        return self._get("workflow_requirements", record_id)

    def update_requirement(self, record_id: str, **fields: Any) -> dict[str, Any]:
        return self._update("workflow_requirements", record_id, fields, {"status"})

    def create_development_task(self, data: dict[str, Any]) -> dict[str, Any]:
        record = {
            **data,
            "id": _id(),
            "status": "pending",
            "self_test_notes": "",
            "commit_notes": "",
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflow_development_tasks (
                    id, requirement_id, title, description, developer, status,
                    self_test_notes, commit_notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _values(
                    record,
                    "id",
                    "requirement_id",
                    "title",
                    "description",
                    "developer",
                    "status",
                    "self_test_notes",
                    "commit_notes",
                    "created_at",
                    "updated_at",
                ),
            )
        return self.get_development_task(record["id"])

    def list_development_tasks(self) -> list[dict[str, Any]]:
        return self._list("workflow_development_tasks")

    def get_development_task(self, record_id: str) -> dict[str, Any]:
        return self._get("workflow_development_tasks", record_id)

    def update_development_task(self, record_id: str, **fields: Any) -> dict[str, Any]:
        return self._update(
            "workflow_development_tasks",
            record_id,
            fields,
            {"status", "self_test_notes", "commit_notes"},
        )

    def create_test_task(self, data: dict[str, Any]) -> dict[str, Any]:
        record = {
            **data,
            "id": _id(),
            "status": "pending",
            "result_notes": "",
            "defect_notes": "",
            "retest_notes": "",
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflow_test_tasks (
                    id, development_task_id, requirement_id, test_cases, tester, status,
                    result_notes, defect_notes, retest_notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _values(
                    record,
                    "id",
                    "development_task_id",
                    "requirement_id",
                    "test_cases",
                    "tester",
                    "status",
                    "result_notes",
                    "defect_notes",
                    "retest_notes",
                    "created_at",
                    "updated_at",
                ),
            )
        return self.get_test_task(record["id"])

    def list_test_tasks(self) -> list[dict[str, Any]]:
        return self._list("workflow_test_tasks")

    def get_test_task(self, record_id: str) -> dict[str, Any]:
        return self._get("workflow_test_tasks", record_id)

    def update_test_task(self, record_id: str, **fields: Any) -> dict[str, Any]:
        return self._update(
            "workflow_test_tasks",
            record_id,
            fields,
            {"status", "result_notes", "defect_notes", "retest_notes"},
        )

    def create_release_task(self, data: dict[str, Any]) -> dict[str, Any]:
        record = {
            **data,
            "id": _id(),
            "status": "pending",
            "server_deploy_result": "",
            "mini_program_test_result": "",
            "release_checklist": data.get("release_checklist") or DEFAULT_RELEASE_CHECKLIST,
            "risk_notes": data.get("risk_notes", ""),
            "known_issues": data.get("known_issues", ""),
            "test_version_url": data.get("test_version_url", ""),
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflow_release_tasks (
                    id, test_task_id, operator, status, server_deploy_result,
                    mini_program_test_result, version, release_notes, rollback_notes,
                    release_checklist, risk_notes, known_issues, test_version_url,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _values(
                    record,
                    "id",
                    "test_task_id",
                    "operator",
                    "status",
                    "server_deploy_result",
                    "mini_program_test_result",
                    "version",
                    "release_notes",
                    "rollback_notes",
                    "release_checklist",
                    "risk_notes",
                    "known_issues",
                    "test_version_url",
                    "created_at",
                    "updated_at",
                ),
            )
        return self.get_release_task(record["id"])

    def list_release_tasks(self) -> list[dict[str, Any]]:
        return self._list("workflow_release_tasks")

    def get_release_task(self, record_id: str) -> dict[str, Any]:
        return self._get("workflow_release_tasks", record_id)

    def update_release_task(self, record_id: str, **fields: Any) -> dict[str, Any]:
        return self._update(
            "workflow_release_tasks",
            record_id,
            fields,
            {
                "status",
                "server_deploy_result",
                "mini_program_test_result",
                "version",
                "release_notes",
                "rollback_notes",
                "release_checklist",
                "risk_notes",
                "known_issues",
                "test_version_url",
            },
        )

    def upsert_acceptance(
        self,
        release_task_id: str,
        *,
        status: str,
        notes: str = "",
        blocker_notes: str = "",
    ) -> dict[str, Any]:
        now = _now()
        acceptance_id = _id()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflow_acceptances (
                    id, release_task_id, status, notes, blocker_notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(release_task_id)
                DO UPDATE SET
                    status = excluded.status,
                    notes = excluded.notes,
                    blocker_notes = excluded.blocker_notes,
                    updated_at = excluded.updated_at
                """,
                (acceptance_id, release_task_id, status, notes, blocker_notes, now, now),
            )
        return self.get_acceptance_by_release(release_task_id)

    def list_acceptances(self) -> list[dict[str, Any]]:
        return self._list("workflow_acceptances")

    def get_acceptance_by_release(self, release_task_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM workflow_acceptances WHERE release_task_id = ?",
                (release_task_id,),
            ).fetchone()
        if row is None:
            raise KeyError(release_task_id)
        return dict(row)

    def _list(self, table: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {table} ORDER BY datetime(created_at) DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def _get(self, table: str, record_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(record_id)
        return dict(row)

    def _update(
        self,
        table: str,
        record_id: str,
        fields: dict[str, Any],
        allowed: set[str],
    ) -> dict[str, Any]:
        clean = {key: value for key, value in fields.items() if value is not None}
        if not clean:
            return self._get(table, record_id)

        clean["updated_at"] = _now()
        assignments = []
        values: list[Any] = []
        for key, value in clean.items():
            if key not in allowed and key != "updated_at":
                raise ValueError(f"cannot update field: {key}")
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(record_id)

        with self._lock, self._connect() as connection:
            connection.execute(f"UPDATE {table} SET {', '.join(assignments)} WHERE id = ?", values)
        return self._get(table, record_id)


def _values(record: dict[str, Any], *keys: str) -> tuple[Any, ...]:
    return tuple(record[key] for key in keys)


def _id() -> str:
    return uuid.uuid4().hex


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
