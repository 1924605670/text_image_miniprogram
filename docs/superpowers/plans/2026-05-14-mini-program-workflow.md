# Mini Program Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable workflow module that lets PMs create requirements, developers submit self-tested work, testers record results, ops records test-version release, and PMs perform final acceptance.

**Architecture:** Add a separate workflow domain beside the existing image generation domain. The backend stores workflow records in SQLite through a focused `WorkflowStore`, exposes REST endpoints in FastAPI, and the existing static frontend gets a lightweight workflow workspace tab without changing the image generation flow.

**Tech Stack:** Python 3.9+, FastAPI, Pydantic v2, SQLite, pytest, vanilla HTML/CSS/JavaScript.

---

## Scope

This plan implements the MVP workflow described in `docs/superpowers/specs/2026-05-14-mini-program-workflow-design.md`.

Included:
- Requirement pool
- Development tasks
- Test tasks
- Release tasks
- Acceptance dashboard
- Backend validation rules for core status transitions
- Frontend screens for creating and moving work through the flow

Not included:
- User login or permissions
- WeChat upload automation
- Remote server deployment automation
- Notifications
- Multi-project support

## File Structure

Create:
- `app/workflow_schemas.py` — Pydantic request/response models and workflow status literals.
- `app/services/workflow_store.py` — SQLite persistence for requirements, development tasks, test tasks, and release tasks.
- `app/services/workflow_service.py` — workflow transition rules and orchestration.
- `tests/test_workflow_store.py` — storage roundtrip and ordering tests.
- `tests/test_workflow_service.py` — business-rule tests for status transitions.
- `tests/test_workflow_api.py` — FastAPI endpoint tests.

Modify:
- `app/main.py` — instantiate workflow store/service and add `/api/workflow/*` endpoints.
- `app/static/index.html` — add top-level mode switch and workflow panels.
- `app/static/app.js` — add workflow API calls and rendering.
- `app/static/styles.css` — add workflow board and form styles.

---

## Task 1: Add workflow schemas

**Files:**
- Create: `app/workflow_schemas.py`
- Test: `tests/test_workflow_service.py`

- [ ] **Step 1: Write failing schema validation tests**

Create `tests/test_workflow_service.py` with this initial content:

```python
import pytest
from pydantic import ValidationError

from app.workflow_schemas import RequirementCreate


def test_requirement_requires_acceptance_criteria() -> None:
    with pytest.raises(ValidationError):
        RequirementCreate(
            title="图片编辑能力",
            background="用户需要二次修改已生成图片",
            business_goal="提升图片产出效率",
            priority="high",
            scope="支持上传参考图并编辑",
            acceptance_criteria="",
            target_version="0.2.0",
        )


def test_requirement_strips_text_fields() -> None:
    request = RequirementCreate(
        title="  图片编辑能力  ",
        background=" 用户需要二次修改已生成图片 ",
        business_goal=" 提升图片产出效率 ",
        priority="high",
        scope=" 支持上传参考图并编辑 ",
        acceptance_criteria=" 能上传参考图并生成编辑结果 ",
        target_version="0.2.0",
    )

    assert request.title == "图片编辑能力"
    assert request.acceptance_criteria == "能上传参考图并生成编辑结果"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
source .venv/bin/activate && pytest tests/test_workflow_service.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.workflow_schemas'`.

- [ ] **Step 3: Create schema module**

Create `app/workflow_schemas.py`:

```python
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


Priority = Literal["low", "medium", "high", "urgent"]
RequirementStatus = Literal["draft", "pending_confirmation", "confirmed", "paused"]
DevelopmentStatus = Literal["pending", "in_progress", "pending_self_test", "self_test_passed", "submitted_to_test"]
TestStatus = Literal["pending", "in_progress", "failed", "retesting", "passed"]
ReleaseStatus = Literal["pending", "in_progress", "submitted_test_version", "failed"]
AcceptanceStatus = Literal["pending", "accepted", "rejected"]


class RequirementCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=120)
    background: str = Field(..., min_length=2, max_length=1000)
    business_goal: str = Field(..., min_length=2, max_length=1000)
    priority: Priority = "medium"
    scope: str = Field(..., min_length=2, max_length=2000)
    acceptance_criteria: str = Field(..., min_length=2, max_length=2000)
    target_version: str = Field(..., min_length=1, max_length=40)

    @field_validator("title", "background", "business_goal", "scope", "acceptance_criteria", "target_version")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return value.strip()


class RequirementUpdate(BaseModel):
    status: Optional[RequirementStatus] = None
    owner: Optional[str] = Field(None, max_length=80)

    @field_validator("owner")
    @classmethod
    def strip_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else value


class RequirementOut(BaseModel):
    id: str
    title: str
    background: str
    business_goal: str
    priority: Priority
    scope: str
    acceptance_criteria: str
    target_version: str
    status: RequirementStatus
    owner: Optional[str] = None
    created_at: str
    updated_at: str


class DevelopmentTaskCreate(BaseModel):
    requirement_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=2, max_length=120)
    description: str = Field(..., min_length=2, max_length=2000)
    developer: str = Field(..., min_length=1, max_length=80)

    @field_validator("requirement_id", "title", "description", "developer")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class DevelopmentTaskUpdate(BaseModel):
    status: Optional[DevelopmentStatus] = None
    self_test_notes: Optional[str] = Field(None, max_length=2000)
    commit_ref: Optional[str] = Field(None, max_length=120)

    @field_validator("self_test_notes", "commit_ref")
    @classmethod
    def strip_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else value


class DevelopmentTaskOut(BaseModel):
    id: str
    requirement_id: str
    title: str
    description: str
    developer: str
    status: DevelopmentStatus
    self_test_notes: Optional[str] = None
    commit_ref: Optional[str] = None
    created_at: str
    updated_at: str


class TestTaskCreate(BaseModel):
    development_task_id: str = Field(..., min_length=1)
    tester: str = Field(..., min_length=1, max_length=80)
    test_cases: str = Field(..., min_length=2, max_length=3000)

    @field_validator("development_task_id", "tester", "test_cases")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class TestTaskUpdate(BaseModel):
    status: Optional[TestStatus] = None
    result_notes: Optional[str] = Field(None, max_length=3000)
    defect_notes: Optional[str] = Field(None, max_length=3000)
    retest_notes: Optional[str] = Field(None, max_length=3000)

    @field_validator("result_notes", "defect_notes", "retest_notes")
    @classmethod
    def strip_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else value


class TestTaskOut(BaseModel):
    id: str
    development_task_id: str
    requirement_id: str
    tester: str
    test_cases: str
    status: TestStatus
    result_notes: Optional[str] = None
    defect_notes: Optional[str] = None
    retest_notes: Optional[str] = None
    created_at: str
    updated_at: str


class ReleaseTaskCreate(BaseModel):
    test_task_id: str = Field(..., min_length=1)
    operator: str = Field(..., min_length=1, max_length=80)
    version: str = Field(..., min_length=1, max_length=40)
    release_notes: str = Field(..., min_length=2, max_length=3000)
    rollback_notes: str = Field(..., min_length=2, max_length=3000)

    @field_validator("test_task_id", "operator", "version", "release_notes", "rollback_notes")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class ReleaseTaskUpdate(BaseModel):
    status: Optional[ReleaseStatus] = None
    server_deploy_result: Optional[str] = Field(None, max_length=3000)
    mini_program_test_result: Optional[str] = Field(None, max_length=3000)
    acceptance_status: Optional[AcceptanceStatus] = None
    acceptance_notes: Optional[str] = Field(None, max_length=3000)

    @field_validator("server_deploy_result", "mini_program_test_result", "acceptance_notes")
    @classmethod
    def strip_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else value


class ReleaseTaskOut(BaseModel):
    id: str
    test_task_id: str
    requirement_id: str
    operator: str
    version: str
    release_notes: str
    rollback_notes: str
    status: ReleaseStatus
    server_deploy_result: Optional[str] = None
    mini_program_test_result: Optional[str] = None
    acceptance_status: AcceptanceStatus
    acceptance_notes: Optional[str] = None
    created_at: str
    updated_at: str


class WorkflowBoardOut(BaseModel):
    requirements: list[RequirementOut]
    development_tasks: list[DevelopmentTaskOut]
    test_tasks: list[TestTaskOut]
    release_tasks: list[ReleaseTaskOut]
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
source .venv/bin/activate && pytest tests/test_workflow_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/workflow_schemas.py tests/test_workflow_service.py
git commit -m "Add workflow schema models"
```

---

## Task 2: Add workflow SQLite store

**Files:**
- Create: `app/services/workflow_store.py`
- Test: `tests/test_workflow_store.py`

- [ ] **Step 1: Write failing storage test**

Create `tests/test_workflow_store.py`:

```python
from pathlib import Path

from app.services.workflow_store import WorkflowStore


def test_workflow_store_roundtrip(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "workflow.db")

    requirement = store.create_requirement(
        title="图片编辑能力",
        background="用户需要二次修改已生成图片",
        business_goal="提升图片产出效率",
        priority="high",
        scope="支持上传参考图并编辑",
        acceptance_criteria="能上传参考图并生成编辑结果",
        target_version="0.2.0",
    )
    development = store.create_development_task(
        requirement_id=requirement["id"],
        title="实现编辑入口",
        description="在结果页增加编辑入口",
        developer="dev-a",
    )
    test_task = store.create_test_task(
        development_task_id=development["id"],
        requirement_id=requirement["id"],
        tester="qa-a",
        test_cases="生成图片后点击编辑入口",
    )
    release = store.create_release_task(
        test_task_id=test_task["id"],
        requirement_id=requirement["id"],
        operator="ops-a",
        version="0.2.0",
        release_notes="提交小程序测试版",
        rollback_notes="回退到 0.1.0",
    )

    assert requirement["status"] == "draft"
    assert development["status"] == "pending"
    assert test_task["status"] == "pending"
    assert release["acceptance_status"] == "pending"
    assert store.list_board()["requirements"][0]["id"] == requirement["id"]


def test_workflow_store_updates_records(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "workflow.db")
    requirement = store.create_requirement(
        title="Prompt 模板库",
        background="用户经常重复输入相同提示词结构",
        business_goal="提升提示词复用效率",
        priority="medium",
        scope="保存和选择常用模板",
        acceptance_criteria="能创建模板并在生成表单中选择",
        target_version="0.2.0",
    )

    updated = store.update_requirement(requirement["id"], status="confirmed", owner="pm-a")

    assert updated["status"] == "confirmed"
    assert updated["owner"] == "pm-a"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
source .venv/bin/activate && pytest tests/test_workflow_store.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.workflow_store'`.

- [ ] **Step 3: Create workflow store**

Create `app/services/workflow_store.py`:

```python
from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
                CREATE TABLE IF NOT EXISTS requirements (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    background TEXT NOT NULL,
                    business_goal TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    acceptance_criteria TEXT NOT NULL,
                    target_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    owner TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS development_tasks (
                    id TEXT PRIMARY KEY,
                    requirement_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    developer TEXT NOT NULL,
                    status TEXT NOT NULL,
                    self_test_notes TEXT,
                    commit_ref TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS test_tasks (
                    id TEXT PRIMARY KEY,
                    development_task_id TEXT NOT NULL,
                    requirement_id TEXT NOT NULL,
                    tester TEXT NOT NULL,
                    test_cases TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_notes TEXT,
                    defect_notes TEXT,
                    retest_notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS release_tasks (
                    id TEXT PRIMARY KEY,
                    test_task_id TEXT NOT NULL,
                    requirement_id TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    version TEXT NOT NULL,
                    release_notes TEXT NOT NULL,
                    rollback_notes TEXT NOT NULL,
                    status TEXT NOT NULL,
                    server_deploy_result TEXT,
                    mini_program_test_result TEXT,
                    acceptance_status TEXT NOT NULL,
                    acceptance_notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def create_requirement(self, **fields: Any) -> dict[str, Any]:
        now = _now()
        record = {
            "id": uuid.uuid4().hex,
            "status": "draft",
            "owner": None,
            "created_at": now,
            "updated_at": now,
            **fields,
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO requirements (
                    id, title, background, business_goal, priority, scope,
                    acceptance_criteria, target_version, status, owner, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"], record["title"], record["background"], record["business_goal"],
                    record["priority"], record["scope"], record["acceptance_criteria"],
                    record["target_version"], record["status"], record["owner"],
                    record["created_at"], record["updated_at"],
                ),
            )
        return self.get_requirement(record["id"])

    def update_requirement(self, requirement_id: str, **fields: Any) -> dict[str, Any]:
        return self._update("requirements", requirement_id, {"status", "owner"}, fields)

    def get_requirement(self, requirement_id: str) -> dict[str, Any]:
        return self._get("requirements", requirement_id)

    def create_development_task(self, **fields: Any) -> dict[str, Any]:
        return self._insert(
            "development_tasks",
            {
                "id": uuid.uuid4().hex,
                "status": "pending",
                "self_test_notes": None,
                "commit_ref": None,
                "created_at": _now(),
                "updated_at": _now(),
                **fields,
            },
            ["id", "requirement_id", "title", "description", "developer", "status", "self_test_notes", "commit_ref", "created_at", "updated_at"],
        )

    def update_development_task(self, task_id: str, **fields: Any) -> dict[str, Any]:
        return self._update("development_tasks", task_id, {"status", "self_test_notes", "commit_ref"}, fields)

    def get_development_task(self, task_id: str) -> dict[str, Any]:
        return self._get("development_tasks", task_id)

    def create_test_task(self, **fields: Any) -> dict[str, Any]:
        return self._insert(
            "test_tasks",
            {
                "id": uuid.uuid4().hex,
                "status": "pending",
                "result_notes": None,
                "defect_notes": None,
                "retest_notes": None,
                "created_at": _now(),
                "updated_at": _now(),
                **fields,
            },
            ["id", "development_task_id", "requirement_id", "tester", "test_cases", "status", "result_notes", "defect_notes", "retest_notes", "created_at", "updated_at"],
        )

    def update_test_task(self, task_id: str, **fields: Any) -> dict[str, Any]:
        return self._update("test_tasks", task_id, {"status", "result_notes", "defect_notes", "retest_notes"}, fields)

    def get_test_task(self, task_id: str) -> dict[str, Any]:
        return self._get("test_tasks", task_id)

    def create_release_task(self, **fields: Any) -> dict[str, Any]:
        return self._insert(
            "release_tasks",
            {
                "id": uuid.uuid4().hex,
                "status": "pending",
                "server_deploy_result": None,
                "mini_program_test_result": None,
                "acceptance_status": "pending",
                "acceptance_notes": None,
                "created_at": _now(),
                "updated_at": _now(),
                **fields,
            },
            ["id", "test_task_id", "requirement_id", "operator", "version", "release_notes", "rollback_notes", "status", "server_deploy_result", "mini_program_test_result", "acceptance_status", "acceptance_notes", "created_at", "updated_at"],
        )

    def update_release_task(self, task_id: str, **fields: Any) -> dict[str, Any]:
        return self._update(
            "release_tasks",
            task_id,
            {"status", "server_deploy_result", "mini_program_test_result", "acceptance_status", "acceptance_notes"},
            fields,
        )

    def get_release_task(self, task_id: str) -> dict[str, Any]:
        return self._get("release_tasks", task_id)

    def list_board(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "requirements": self._list("requirements"),
            "development_tasks": self._list("development_tasks"),
            "test_tasks": self._list("test_tasks"),
            "release_tasks": self._list("release_tasks"),
        }

    def _insert(self, table: str, record: dict[str, Any], columns: list[str]) -> dict[str, Any]:
        placeholders = ", ".join(["?"] * len(columns))
        with self._lock, self._connect() as connection:
            connection.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                [record[column] for column in columns],
            )
        return self._get(table, record["id"])

    def _update(self, table: str, record_id: str, allowed: set[str], fields: dict[str, Any]) -> dict[str, Any]:
        clean_fields = {key: value for key, value in fields.items() if value is not None}
        if not clean_fields:
            return self._get(table, record_id)
        clean_fields["updated_at"] = _now()
        allowed_with_timestamp = set(allowed) | {"updated_at"}
        assignments = []
        values = []
        for key, value in clean_fields.items():
            if key not in allowed_with_timestamp:
                raise ValueError(f"cannot update field: {key}")
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(record_id)
        with self._lock, self._connect() as connection:
            connection.execute(f"UPDATE {table} SET {', '.join(assignments)} WHERE id = ?", values)
        return self._get(table, record_id)

    def _get(self, table: str, record_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(record_id)
        return dict(row)

    def _list(self, table: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(f"SELECT * FROM {table} ORDER BY datetime(created_at) DESC").fetchall()
        return [dict(row) for row in rows]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 4: Run storage tests**

Run:

```bash
source .venv/bin/activate && pytest tests/test_workflow_store.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/workflow_store.py tests/test_workflow_store.py
git commit -m "Add workflow SQLite store"
```

---

## Task 3: Add workflow service rules

**Files:**
- Create: `app/services/workflow_service.py`
- Modify: `tests/test_workflow_service.py`

- [ ] **Step 1: Add failing service-rule tests**

Append to `tests/test_workflow_service.py`:

```python
from pathlib import Path

from app.services.workflow_service import WorkflowRuleError, WorkflowService
from app.services.workflow_store import WorkflowStore
from app.workflow_schemas import (
    DevelopmentTaskCreate,
    DevelopmentTaskUpdate,
    ReleaseTaskCreate,
    ReleaseTaskUpdate,
    RequirementCreate,
    RequirementUpdate,
    TestTaskCreate,
    TestTaskUpdate,
)


def service(tmp_path: Path) -> WorkflowService:
    return WorkflowService(WorkflowStore(tmp_path / "workflow.db"))


def create_confirmed_requirement(workflow: WorkflowService) -> dict:
    requirement = workflow.create_requirement(
        RequirementCreate(
            title="图片编辑能力",
            background="用户需要二次修改已生成图片",
            business_goal="提升图片产出效率",
            priority="high",
            scope="支持上传参考图并编辑",
            acceptance_criteria="能上传参考图并生成编辑结果",
            target_version="0.2.0",
        )
    )
    return workflow.update_requirement(requirement["id"], RequirementUpdate(status="confirmed", owner="pm-a"))


def test_development_task_requires_confirmed_requirement(tmp_path: Path) -> None:
    workflow = service(tmp_path)
    requirement = workflow.create_requirement(
        RequirementCreate(
            title="Prompt 模板库",
            background="用户经常重复输入相同提示词结构",
            business_goal="提升提示词复用效率",
            priority="medium",
            scope="保存和选择常用模板",
            acceptance_criteria="能创建模板并在生成表单中选择",
            target_version="0.2.0",
        )
    )

    with pytest.raises(WorkflowRuleError, match="需求未确认"):
        workflow.create_development_task(
            DevelopmentTaskCreate(
                requirement_id=requirement["id"],
                title="实现模板保存",
                description="保存用户常用提示词模板",
                developer="dev-a",
            )
        )


def test_submit_to_test_requires_self_test_notes(tmp_path: Path) -> None:
    workflow = service(tmp_path)
    requirement = create_confirmed_requirement(workflow)
    task = workflow.create_development_task(
        DevelopmentTaskCreate(
            requirement_id=requirement["id"],
            title="实现编辑入口",
            description="在结果页增加编辑入口",
            developer="dev-a",
        )
    )

    with pytest.raises(WorkflowRuleError, match="自测说明"):
        workflow.update_development_task(task["id"], DevelopmentTaskUpdate(status="submitted_to_test"))


def test_release_requires_passed_test(tmp_path: Path) -> None:
    workflow = service(tmp_path)
    requirement = create_confirmed_requirement(workflow)
    development = workflow.create_development_task(
        DevelopmentTaskCreate(
            requirement_id=requirement["id"],
            title="实现编辑入口",
            description="在结果页增加编辑入口",
            developer="dev-a",
        )
    )
    development = workflow.update_development_task(
        development["id"],
        DevelopmentTaskUpdate(status="submitted_to_test", self_test_notes="主流程通过", commit_ref="abc123"),
    )
    test_task = workflow.create_test_task(
        TestTaskCreate(
            development_task_id=development["id"],
            tester="qa-a",
            test_cases="打开图片结果后进入编辑",
        )
    )

    with pytest.raises(WorkflowRuleError, match="测试未通过"):
        workflow.create_release_task(
            ReleaseTaskCreate(
                test_task_id=test_task["id"],
                operator="ops-a",
                version="0.2.0",
                release_notes="提交测试版",
                rollback_notes="回退到 0.1.0",
            )
        )


def test_acceptance_requires_submitted_test_version(tmp_path: Path) -> None:
    workflow = service(tmp_path)
    requirement = create_confirmed_requirement(workflow)
    development = workflow.create_development_task(
        DevelopmentTaskCreate(
            requirement_id=requirement["id"],
            title="实现编辑入口",
            description="在结果页增加编辑入口",
            developer="dev-a",
        )
    )
    workflow.update_development_task(
        development["id"],
        DevelopmentTaskUpdate(status="submitted_to_test", self_test_notes="主流程通过", commit_ref="abc123"),
    )
    test_task = workflow.create_test_task(
        TestTaskCreate(
            development_task_id=development["id"],
            tester="qa-a",
            test_cases="打开图片结果后进入编辑",
        )
    )
    workflow.update_test_task(test_task["id"], TestTaskUpdate(status="passed", result_notes="验收标准通过"))
    release = workflow.create_release_task(
        ReleaseTaskCreate(
            test_task_id=test_task["id"],
            operator="ops-a",
            version="0.2.0",
            release_notes="提交测试版",
            rollback_notes="回退到 0.1.0",
        )
    )

    with pytest.raises(WorkflowRuleError, match="小程序测试版"):
        workflow.update_release_task(release["id"], ReleaseTaskUpdate(acceptance_status="accepted"))
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
source .venv/bin/activate && pytest tests/test_workflow_service.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.workflow_service'`.

- [ ] **Step 3: Create workflow service**

Create `app/services/workflow_service.py`:

```python
from __future__ import annotations

from app.services.workflow_store import WorkflowStore
from app.workflow_schemas import (
    DevelopmentTaskCreate,
    DevelopmentTaskUpdate,
    ReleaseTaskCreate,
    ReleaseTaskUpdate,
    RequirementCreate,
    RequirementUpdate,
    TestTaskCreate,
    TestTaskUpdate,
)


class WorkflowRuleError(ValueError):
    pass


class WorkflowService:
    def __init__(self, store: WorkflowStore) -> None:
        self.store = store

    def create_requirement(self, request: RequirementCreate) -> dict:
        return self.store.create_requirement(**request.model_dump())

    def update_requirement(self, requirement_id: str, request: RequirementUpdate) -> dict:
        fields = request.model_dump(exclude_none=True)
        return self.store.update_requirement(requirement_id, **fields)

    def create_development_task(self, request: DevelopmentTaskCreate) -> dict:
        requirement = self.store.get_requirement(request.requirement_id)
        if requirement["status"] != "confirmed":
            raise WorkflowRuleError("需求未确认，不能进入开发")
        return self.store.create_development_task(**request.model_dump())

    def update_development_task(self, task_id: str, request: DevelopmentTaskUpdate) -> dict:
        current = self.store.get_development_task(task_id)
        fields = request.model_dump(exclude_none=True)
        next_status = fields.get("status")
        self_test_notes = fields.get("self_test_notes") or current.get("self_test_notes")
        if next_status == "submitted_to_test" and not self_test_notes:
            raise WorkflowRuleError("提交测试前必须填写自测说明")
        return self.store.update_development_task(task_id, **fields)

    def create_test_task(self, request: TestTaskCreate) -> dict:
        development = self.store.get_development_task(request.development_task_id)
        if development["status"] != "submitted_to_test":
            raise WorkflowRuleError("开发任务未提交测试")
        return self.store.create_test_task(requirement_id=development["requirement_id"], **request.model_dump())

    def update_test_task(self, task_id: str, request: TestTaskUpdate) -> dict:
        fields = request.model_dump(exclude_none=True)
        return self.store.update_test_task(task_id, **fields)

    def create_release_task(self, request: ReleaseTaskCreate) -> dict:
        test_task = self.store.get_test_task(request.test_task_id)
        if test_task["status"] != "passed":
            raise WorkflowRuleError("测试未通过，不能进入发布")
        return self.store.create_release_task(requirement_id=test_task["requirement_id"], **request.model_dump())

    def update_release_task(self, task_id: str, request: ReleaseTaskUpdate) -> dict:
        current = self.store.get_release_task(task_id)
        fields = request.model_dump(exclude_none=True)
        next_status = fields.get("status") or current["status"]
        server_result = fields.get("server_deploy_result") or current.get("server_deploy_result")
        mini_result = fields.get("mini_program_test_result") or current.get("mini_program_test_result")
        if next_status == "submitted_test_version" and (not server_result or not mini_result):
            raise WorkflowRuleError("提交测试版前必须记录服务器部署结果和小程序测试版提交结果")
        if fields.get("acceptance_status") in {"accepted", "rejected"} and next_status != "submitted_test_version":
            raise WorkflowRuleError("小程序测试版提交成功后才能验收")
        return self.store.update_release_task(task_id, **fields)

    def board(self) -> dict:
        return self.store.list_board()
```

- [ ] **Step 4: Run service tests**

Run:

```bash
source .venv/bin/activate && pytest tests/test_workflow_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/workflow_service.py tests/test_workflow_service.py
git commit -m "Add workflow transition rules"
```

---

## Task 4: Add workflow API endpoints

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_workflow_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_workflow_api.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


def test_workflow_requirement_to_board_api() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/workflow/requirements",
            json={
                "title": "图片编辑能力",
                "background": "用户需要二次修改已生成图片",
                "business_goal": "提升图片产出效率",
                "priority": "high",
                "scope": "支持上传参考图并编辑",
                "acceptance_criteria": "能上传参考图并生成编辑结果",
                "target_version": "0.2.0",
            },
        )
        assert response.status_code == 201
        requirement = response.json()

        response = client.patch(
            f"/api/workflow/requirements/{requirement['id']}",
            json={"status": "confirmed", "owner": "pm-a"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "confirmed"

        response = client.get("/api/workflow/board")
        assert response.status_code == 200
        assert response.json()["requirements"][0]["id"] == requirement["id"]


def test_workflow_api_returns_rule_error() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/workflow/requirements",
            json={
                "title": "Prompt 模板库",
                "background": "用户经常重复输入相同提示词结构",
                "business_goal": "提升提示词复用效率",
                "priority": "medium",
                "scope": "保存和选择常用模板",
                "acceptance_criteria": "能创建模板并在生成表单中选择",
                "target_version": "0.2.0",
            },
        )
        requirement = response.json()

        response = client.post(
            "/api/workflow/development-tasks",
            json={
                "requirement_id": requirement["id"],
                "title": "实现模板保存",
                "description": "保存用户常用提示词模板",
                "developer": "dev-a",
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "需求未确认，不能进入开发"
```

- [ ] **Step 2: Run API tests to verify they fail**

Run:

```bash
source .venv/bin/activate && pytest tests/test_workflow_api.py -v
```

Expected: FAIL with `404 Not Found` for `/api/workflow/requirements`.

- [ ] **Step 3: Modify imports and service setup in `app/main.py`**

Add these imports near the existing imports:

```python
from app.services.workflow_service import WorkflowRuleError, WorkflowService
from app.services.workflow_store import WorkflowStore
from app.workflow_schemas import (
    DevelopmentTaskCreate,
    DevelopmentTaskOut,
    DevelopmentTaskUpdate,
    ReleaseTaskCreate,
    ReleaseTaskOut,
    ReleaseTaskUpdate,
    RequirementCreate,
    RequirementOut,
    RequirementUpdate,
    TestTaskCreate,
    TestTaskOut,
    TestTaskUpdate,
    WorkflowBoardOut,
)
```

Add this after `generation_service = GenerationService(...)`:

```python
workflow_store = WorkflowStore(settings.database_path)
workflow_service = WorkflowService(workflow_store)
```

- [ ] **Step 4: Add workflow endpoints to `app/main.py` before `_job_out`**

```python
@app.get("/api/workflow/board", response_model=WorkflowBoardOut)
async def workflow_board() -> WorkflowBoardOut:
    return WorkflowBoardOut(**workflow_service.board())


@app.post("/api/workflow/requirements", response_model=RequirementOut, status_code=201)
async def create_workflow_requirement(request: RequirementCreate) -> RequirementOut:
    return RequirementOut(**workflow_service.create_requirement(request))


@app.patch("/api/workflow/requirements/{requirement_id}", response_model=RequirementOut)
async def update_workflow_requirement(requirement_id: str, request: RequirementUpdate) -> RequirementOut:
    try:
        return RequirementOut(**workflow_service.update_requirement(requirement_id, request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="requirement not found") from exc


@app.post("/api/workflow/development-tasks", response_model=DevelopmentTaskOut, status_code=201)
async def create_workflow_development_task(request: DevelopmentTaskCreate) -> DevelopmentTaskOut:
    try:
        return DevelopmentTaskOut(**workflow_service.create_development_task(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="requirement not found") from exc
    except WorkflowRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/workflow/development-tasks/{task_id}", response_model=DevelopmentTaskOut)
async def update_workflow_development_task(task_id: str, request: DevelopmentTaskUpdate) -> DevelopmentTaskOut:
    try:
        return DevelopmentTaskOut(**workflow_service.update_development_task(task_id, request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="development task not found") from exc
    except WorkflowRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workflow/test-tasks", response_model=TestTaskOut, status_code=201)
async def create_workflow_test_task(request: TestTaskCreate) -> TestTaskOut:
    try:
        return TestTaskOut(**workflow_service.create_test_task(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="development task not found") from exc
    except WorkflowRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/workflow/test-tasks/{task_id}", response_model=TestTaskOut)
async def update_workflow_test_task(task_id: str, request: TestTaskUpdate) -> TestTaskOut:
    try:
        return TestTaskOut(**workflow_service.update_test_task(task_id, request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="test task not found") from exc


@app.post("/api/workflow/release-tasks", response_model=ReleaseTaskOut, status_code=201)
async def create_workflow_release_task(request: ReleaseTaskCreate) -> ReleaseTaskOut:
    try:
        return ReleaseTaskOut(**workflow_service.create_release_task(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="test task not found") from exc
    except WorkflowRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/workflow/release-tasks/{task_id}", response_model=ReleaseTaskOut)
async def update_workflow_release_task(task_id: str, request: ReleaseTaskUpdate) -> ReleaseTaskOut:
    try:
        return ReleaseTaskOut(**workflow_service.update_release_task(task_id, request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release task not found") from exc
    except WorkflowRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] **Step 5: Run API tests**

Run:

```bash
source .venv/bin/activate && pytest tests/test_workflow_api.py -v
```

Expected: PASS.

- [ ] **Step 6: Run backend workflow tests**

Run:

```bash
source .venv/bin/activate && pytest tests/test_workflow_store.py tests/test_workflow_service.py tests/test_workflow_api.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/main.py tests/test_workflow_api.py
git commit -m "Expose workflow API endpoints"
```

---

## Task 5: Add workflow UI shell

**Files:**
- Modify: `app/static/index.html`
- Modify: `app/static/styles.css`

- [ ] **Step 1: Add a mode switch to `app/static/index.html`**

Insert this block immediately inside `<body>`, before `<div class="app-shell">`:

```html
    <nav class="mode-switch" aria-label="工作区切换">
      <button id="imageModeButton" class="active" type="button">文生图</button>
      <button id="workflowModeButton" type="button">产品流程</button>
    </nav>
```

Change the existing `<div class="app-shell">` to:

```html
    <div id="imageWorkspace" class="app-shell">
```

Insert this workflow workspace before `</body>` and after the existing image workspace closing `</div>`:

```html
    <div id="workflowWorkspace" class="workflow-shell hidden">
      <aside class="panel workflow-form-panel">
        <div class="brand-row">
          <div>
            <p class="eyebrow">Workflow</p>
            <h1>产品协作流程</h1>
          </div>
        </div>

        <form id="requirementForm" class="stack">
          <label class="field">
            <span>需求标题</span>
            <input name="title" required minlength="2" maxlength="120" placeholder="例如：图片编辑能力" />
          </label>
          <label class="field">
            <span>背景</span>
            <textarea name="background" rows="3" required placeholder="为什么要做这个需求"></textarea>
          </label>
          <label class="field">
            <span>业务目标</span>
            <textarea name="business_goal" rows="3" required placeholder="希望达成什么业务结果"></textarea>
          </label>
          <label class="field">
            <span>优先级</span>
            <select name="priority">
              <option value="low">低</option>
              <option value="medium" selected>中</option>
              <option value="high">高</option>
              <option value="urgent">紧急</option>
            </select>
          </label>
          <label class="field">
            <span>功能范围</span>
            <textarea name="scope" rows="4" required placeholder="本次做什么，不做什么"></textarea>
          </label>
          <label class="field">
            <span>验收标准</span>
            <textarea name="acceptance_criteria" rows="4" required placeholder="满足哪些条件才算完成"></textarea>
          </label>
          <label class="field">
            <span>期望版本</span>
            <input name="target_version" required placeholder="例如：0.2.0" />
          </label>
          <button class="primary-action" type="submit">创建需求</button>
        </form>
      </aside>

      <main class="workflow-main">
        <section class="toolbar">
          <div>
            <p class="eyebrow">Acceptance Board</p>
            <h2>小程序测试版验收看板</h2>
          </div>
          <button id="refreshWorkflow" class="secondary-action" type="button">刷新流程</button>
        </section>
        <section id="workflowBoard" class="workflow-board"></section>
      </main>
    </div>
```

- [ ] **Step 2: Add workflow shell styles to `app/static/styles.css`**

Append this CSS before the existing `@media` block:

```css
.mode-switch {
  display: flex;
  gap: 8px;
  padding: 12px 16px 0;
  background: var(--bg);
}

.mode-switch button {
  min-height: 38px;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0 16px;
  color: var(--muted);
  background: #fffefa;
  font-weight: 800;
}

.mode-switch button.active {
  color: #fff;
  border-color: var(--accent);
  background: var(--accent);
}

.hidden {
  display: none !important;
}

.workflow-shell {
  display: grid;
  grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
  gap: 16px;
  min-height: calc(100vh - 62px);
  padding: 16px;
}

.workflow-main {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  border: 1px solid var(--line);
  background: var(--paper);
  box-shadow: var(--shadow);
  min-width: 0;
}

.workflow-board {
  display: grid;
  grid-template-columns: repeat(4, minmax(220px, 1fr));
  gap: 12px;
  padding: 16px;
  overflow: auto;
}

.workflow-column {
  display: grid;
  align-content: start;
  gap: 10px;
  min-width: 0;
}

.workflow-column h3 {
  margin: 0;
  font-size: 16px;
}

.workflow-card {
  display: grid;
  gap: 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  background: #fffefa;
}

.workflow-card h4 {
  margin: 0;
  line-height: 1.3;
}

.workflow-card p {
  margin: 0;
  color: var(--muted);
  line-height: 1.45;
}

.workflow-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.workflow-card-actions button {
  min-height: 32px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 0 10px;
  background: #fffefa;
  font-weight: 800;
}
```

- [ ] **Step 3: Add responsive styles**

Inside the existing `@media (max-width: 1180px)` block, add:

```css
  .workflow-shell {
    grid-template-columns: 1fr;
  }

  .workflow-board {
    grid-template-columns: 1fr;
  }
```

- [ ] **Step 4: Manually verify static HTML loads**

Run:

```bash
source .venv/bin/activate && uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` and verify:
- The top switch shows `文生图` and `产品流程`.
- The existing image workspace is visible by default.
- No browser console errors are introduced by the HTML/CSS change.

- [ ] **Step 5: Commit**

```bash
git add app/static/index.html app/static/styles.css
git commit -m "Add workflow UI shell"
```

---

## Task 6: Add workflow frontend behavior

**Files:**
- Modify: `app/static/app.js`

- [ ] **Step 1: Add workflow DOM references**

Near the existing top-level DOM constants in `app/static/app.js`, add:

```javascript
const imageWorkspace = document.querySelector("#imageWorkspace");
const workflowWorkspace = document.querySelector("#workflowWorkspace");
const imageModeButton = document.querySelector("#imageModeButton");
const workflowModeButton = document.querySelector("#workflowModeButton");
const requirementForm = document.querySelector("#requirementForm");
const workflowBoard = document.querySelector("#workflowBoard");
const refreshWorkflow = document.querySelector("#refreshWorkflow");
```

- [ ] **Step 2: Wire workflow events**

Inside `wireEvents()`, after `refreshHistory.addEventListener("click", loadHistory);`, add:

```javascript
  imageModeButton.addEventListener("click", () => switchMode("image"));
  workflowModeButton.addEventListener("click", async () => {
    switchMode("workflow");
    await loadWorkflowBoard();
  });
  refreshWorkflow.addEventListener("click", loadWorkflowBoard);
  requirementForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await createRequirement();
  });
```

- [ ] **Step 3: Add workflow functions before `escapeHtml`**

Add this block before the existing `escapeHtml` function:

```javascript
function switchMode(mode) {
  const workflowActive = mode === "workflow";
  imageWorkspace.classList.toggle("hidden", workflowActive);
  workflowWorkspace.classList.toggle("hidden", !workflowActive);
  imageModeButton.classList.toggle("active", !workflowActive);
  workflowModeButton.classList.toggle("active", workflowActive);
}

async function createRequirement() {
  const data = new FormData(requirementForm);
  const payload = {
    title: String(data.get("title") || "").trim(),
    background: String(data.get("background") || "").trim(),
    business_goal: String(data.get("business_goal") || "").trim(),
    priority: String(data.get("priority") || "medium"),
    scope: String(data.get("scope") || "").trim(),
    acceptance_criteria: String(data.get("acceptance_criteria") || "").trim(),
    target_version: String(data.get("target_version") || "").trim(),
  };
  await api("/api/workflow/requirements", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  requirementForm.reset();
  await loadWorkflowBoard();
}

async function loadWorkflowBoard() {
  try {
    const board = await api("/api/workflow/board");
    renderWorkflowBoard(board);
  } catch (error) {
    workflowBoard.innerHTML = `<div class="error-box">${escapeHtml(error.message)}</div>`;
  }
}

function renderWorkflowBoard(board) {
  workflowBoard.innerHTML = `
    ${workflowColumn("需求池", board.requirements, requirementCard)}
    ${workflowColumn("开发任务", board.development_tasks, developmentCard)}
    ${workflowColumn("测试任务", board.test_tasks, testTaskCard)}
    ${workflowColumn("发布验收", board.release_tasks, releaseTaskCard)}
  `;
  bindWorkflowActions();
}

function workflowColumn(title, items, renderer) {
  return `
    <section class="workflow-column">
      <h3>${title}</h3>
      ${items.length ? items.map(renderer).join("") : `<article class="workflow-card"><p>暂无记录</p></article>`}
    </section>
  `;
}

function requirementCard(item) {
  return `
    <article class="workflow-card" data-requirement-id="${item.id}">
      <h4>${escapeHtml(item.title)}</h4>
      <p>${escapeHtml(priorityText(item.priority))} · ${escapeHtml(requirementStatusText(item.status))} · ${escapeHtml(item.target_version)}</p>
      <p>${escapeHtml(item.business_goal)}</p>
      <div class="workflow-card-actions">
        ${item.status !== "confirmed" ? `<button type="button" data-action="confirm-requirement">确认需求</button>` : ""}
        ${item.status === "confirmed" ? `<button type="button" data-action="create-development">创建开发任务</button>` : ""}
      </div>
    </article>
  `;
}

function developmentCard(item) {
  return `
    <article class="workflow-card" data-development-id="${item.id}">
      <h4>${escapeHtml(item.title)}</h4>
      <p>${escapeHtml(developmentStatusText(item.status))} · ${escapeHtml(item.developer)}</p>
      <p>${escapeHtml(item.description)}</p>
      <div class="workflow-card-actions">
        ${item.status !== "submitted_to_test" ? `<button type="button" data-action="submit-development">提交测试</button>` : `<button type="button" data-action="create-test">创建测试任务</button>`}
      </div>
    </article>
  `;
}

function testTaskCard(item) {
  return `
    <article class="workflow-card" data-test-id="${item.id}">
      <h4>测试任务</h4>
      <p>${escapeHtml(testStatusText(item.status))} · ${escapeHtml(item.tester)}</p>
      <p>${escapeHtml(item.test_cases)}</p>
      <div class="workflow-card-actions">
        ${item.status !== "passed" ? `<button type="button" data-action="pass-test">测试通过</button>` : `<button type="button" data-action="create-release">创建发布任务</button>`}
      </div>
    </article>
  `;
}

function releaseTaskCard(item) {
  return `
    <article class="workflow-card" data-release-id="${item.id}">
      <h4>${escapeHtml(item.version)}</h4>
      <p>${escapeHtml(releaseStatusText(item.status))} · ${escapeHtml(item.operator)} · ${escapeHtml(acceptanceText(item.acceptance_status))}</p>
      <p>${escapeHtml(item.release_notes)}</p>
      <div class="workflow-card-actions">
        ${item.status !== "submitted_test_version" ? `<button type="button" data-action="submit-release">提交测试版</button>` : ""}
        ${item.status === "submitted_test_version" && item.acceptance_status === "pending" ? `<button type="button" data-action="accept-release">产品验收通过</button>` : ""}
      </div>
    </article>
  `;
}

function bindWorkflowActions() {
  workflowBoard.querySelectorAll("[data-action='confirm-requirement']").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.closest("[data-requirement-id]").dataset.requirementId;
      await api(`/api/workflow/requirements/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "confirmed", owner: "pm" }),
      });
      await loadWorkflowBoard();
    });
  });
  workflowBoard.querySelectorAll("[data-action='create-development']").forEach((button) => {
    button.addEventListener("click", async () => {
      const card = button.closest("[data-requirement-id]");
      await api("/api/workflow/development-tasks", {
        method: "POST",
        body: JSON.stringify({
          requirement_id: card.dataset.requirementId,
          title: `开发：${card.querySelector("h4").textContent}`,
          description: "实现已确认需求并完成开发自测",
          developer: "developer",
        }),
      });
      await loadWorkflowBoard();
    });
  });
  workflowBoard.querySelectorAll("[data-action='submit-development']").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.closest("[data-development-id]").dataset.developmentId;
      await api(`/api/workflow/development-tasks/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "submitted_to_test", self_test_notes: "主流程和异常输入已自测", commit_ref: "local" }),
      });
      await loadWorkflowBoard();
    });
  });
  workflowBoard.querySelectorAll("[data-action='create-test']").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.closest("[data-development-id]").dataset.developmentId;
      await api("/api/workflow/test-tasks", {
        method: "POST",
        body: JSON.stringify({ development_task_id: id, tester: "tester", test_cases: "覆盖验收标准、主流程、异常输入和兼容性" }),
      });
      await loadWorkflowBoard();
    });
  });
  workflowBoard.querySelectorAll("[data-action='pass-test']").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.closest("[data-test-id]").dataset.testId;
      await api(`/api/workflow/test-tasks/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "passed", result_notes: "验收标准通过" }),
      });
      await loadWorkflowBoard();
    });
  });
  workflowBoard.querySelectorAll("[data-action='create-release']").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.closest("[data-test-id]").dataset.testId;
      await api("/api/workflow/release-tasks", {
        method: "POST",
        body: JSON.stringify({ test_task_id: id, operator: "ops", version: "test", release_notes: "部署服务器并提交小程序测试版", rollback_notes: "回退到上一测试版本" }),
      });
      await loadWorkflowBoard();
    });
  });
  workflowBoard.querySelectorAll("[data-action='submit-release']").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.closest("[data-release-id]").dataset.releaseId;
      await api(`/api/workflow/release-tasks/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "submitted_test_version", server_deploy_result: "服务器部署完成", mini_program_test_result: "小程序测试版提交成功" }),
      });
      await loadWorkflowBoard();
    });
  });
  workflowBoard.querySelectorAll("[data-action='accept-release']").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.closest("[data-release-id]").dataset.releaseId;
      await api(`/api/workflow/release-tasks/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ acceptance_status: "accepted", acceptance_notes: "产品验收通过" }),
      });
      await loadWorkflowBoard();
    });
  });
}

function priorityText(priority) {
  return { low: "低", medium: "中", high: "高", urgent: "紧急" }[priority] || priority;
}

function requirementStatusText(status) {
  return { draft: "草稿", pending_confirmation: "待确认", confirmed: "已确认", paused: "暂缓" }[status] || status;
}

function developmentStatusText(status) {
  return { pending: "待开发", in_progress: "开发中", pending_self_test: "待自测", self_test_passed: "自测通过", submitted_to_test: "提交测试" }[status] || status;
}

function testStatusText(status) {
  return { pending: "待测试", in_progress: "测试中", failed: "测试失败", retesting: "复测中", passed: "测试通过" }[status] || status;
}

function releaseStatusText(status) {
  return { pending: "待发布", in_progress: "发布中", submitted_test_version: "已提交测试版", failed: "发布失败" }[status] || status;
}

function acceptanceText(status) {
  return { pending: "待验收", accepted: "验收通过", rejected: "验收拒绝" }[status] || status;
}
```

- [ ] **Step 2: Run backend tests before browser verification**

Run:

```bash
source .venv/bin/activate && pytest tests/test_workflow_store.py tests/test_workflow_service.py tests/test_workflow_api.py -v
```

Expected: PASS.

- [ ] **Step 3: Browser verify the golden workflow path**

Run:

```bash
source .venv/bin/activate && uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` and perform:
1. Click `产品流程`.
2. Create a requirement.
3. Click `确认需求`.
4. Click `创建开发任务`.
5. Click `提交测试`.
6. Click `创建测试任务`.
7. Click `测试通过`.
8. Click `创建发布任务`.
9. Click `提交测试版`.
10. Click `产品验收通过`.

Expected:
- The record moves across the workflow columns.
- No browser console errors appear.
- Refreshing the page and entering `产品流程` shows persisted records.
- Clicking `文生图` still shows the original generation workspace.

- [ ] **Step 4: Commit**

```bash
git add app/static/app.js
git commit -m "Add workflow frontend behavior"
```

---

## Task 7: Full verification and release-readiness check

**Files:**
- Modify only if verification finds a bug.

- [ ] **Step 1: Run full test suite**

Run:

```bash
source .venv/bin/activate && pytest -v
```

Expected: all tests PASS.

- [ ] **Step 2: Verify existing image generation UI still loads**

Run:

```bash
source .venv/bin/activate && uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` and verify:
- Default mode is `文生图`.
- Existing prompt form renders.
- History panel renders.
- Provider health badge still updates.

- [ ] **Step 3: Verify workflow edge cases in browser**

In `产品流程`, verify:
- Empty requirement form cannot submit because required fields are enforced by the browser.
- A newly created requirement only shows `确认需求`, not `创建开发任务`.
- A confirmed requirement shows `创建开发任务`.
- A release cannot be accepted before `提交测试版` because the UI does not show `产品验收通过` until after submission.

- [ ] **Step 4: Inspect git status**

Run:

```bash
git status --short
```

Expected: no uncommitted changes.

If changes exist because bugs were fixed during verification, commit them with:

```bash
git add <changed-files>
git commit -m "Fix workflow verification issues"
```

---

## Spec Coverage Review

- Requirement pool: Task 1, Task 2, Task 4, Task 5, Task 6.
- Development tasks and self-test gate: Task 1, Task 2, Task 3, Task 4, Task 6.
- Test tasks and pass/fail gate: Task 1, Task 2, Task 3, Task 4, Task 6.
- Release tasks and test-version submission: Task 1, Task 2, Task 3, Task 4, Task 6.
- Acceptance dashboard: Task 4, Task 5, Task 6.
- Validation rules: Task 3 and Task 4.
- Testing strategy: Task 1 through Task 4 plus Task 7.

## Execution Notes

Use the existing virtual environment for all Python commands:

```bash
source .venv/bin/activate
```

The system Python may not have project dependencies installed. Do not use bare `python3 -m pytest` unless dependencies have been installed into that interpreter.
