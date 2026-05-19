from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


Priority = Literal["low", "medium", "high", "urgent"]
RequirementStatus = Literal["draft", "pending_confirmation", "confirmed", "paused"]
DevelopmentStatus = Literal[
    "pending",
    "in_progress",
    "pending_self_test",
    "self_test_passed",
    "submitted_to_test",
]
TestStatus = Literal["pending", "in_progress", "failed", "retesting", "passed"]
ReleaseStatus = Literal["pending", "in_progress", "submitted_test_version", "failed"]
AcceptanceStatus = Literal["pending", "accepted", "rejected"]

DEFAULT_RELEASE_CHECKLIST = (
    "- [ ] 服务器部署健康检查通过\n"
    "- [ ] 小程序测试版提交记录完整\n"
    "- [ ] 回滚方案和负责人已确认"
)
DEFAULT_COMPLETED_RELEASE_CHECKLIST = DEFAULT_RELEASE_CHECKLIST.replace("[ ]", "[x]")


class WorkflowBaseModel(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class RequirementCreate(WorkflowBaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    background: str = Field("", max_length=1200)
    business_goal: str = Field(..., min_length=1, max_length=1200)
    priority: Priority = "medium"
    scope: str = Field(..., min_length=1, max_length=2000)
    acceptance_criteria: str = Field(..., min_length=1, max_length=2000)
    expected_version: str = Field("", max_length=80)


class RequirementOut(RequirementCreate):
    id: str
    status: RequirementStatus
    created_at: str
    updated_at: str


class DevelopmentTaskCreate(WorkflowBaseModel):
    requirement_id: str
    title: str = Field(..., min_length=1, max_length=120)
    description: str = Field(..., min_length=1, max_length=2000)
    developer: str = Field(..., min_length=1, max_length=80)


class DevelopmentTaskUpdate(WorkflowBaseModel):
    status: Optional[DevelopmentStatus] = None
    self_test_notes: Optional[str] = Field(None, max_length=2000)
    commit_notes: Optional[str] = Field(None, max_length=1200)


class DevelopmentTaskOut(DevelopmentTaskCreate):
    id: str
    status: DevelopmentStatus
    self_test_notes: str
    commit_notes: str
    created_at: str
    updated_at: str


class TestTaskCreate(WorkflowBaseModel):
    development_task_id: str
    test_cases: str = Field(..., min_length=1, max_length=3000)
    tester: str = Field(..., min_length=1, max_length=80)


class TestTaskUpdate(WorkflowBaseModel):
    status: Optional[TestStatus] = None
    result_notes: Optional[str] = Field(None, max_length=3000)
    defect_notes: Optional[str] = Field(None, max_length=3000)
    retest_notes: Optional[str] = Field(None, max_length=3000)


class TestTaskOut(TestTaskCreate):
    id: str
    requirement_id: str
    status: TestStatus
    result_notes: str
    defect_notes: str
    retest_notes: str
    created_at: str
    updated_at: str


class ReleaseTaskCreate(WorkflowBaseModel):
    test_task_id: str
    operator: str = Field(..., min_length=1, max_length=80)
    version: str = Field("test", max_length=80)
    release_notes: str = Field("", max_length=2000)
    rollback_notes: str = Field("", max_length=2000)
    release_checklist: str = Field(DEFAULT_RELEASE_CHECKLIST, max_length=3000)
    risk_notes: str = Field("", max_length=3000)
    known_issues: str = Field("", max_length=3000)
    test_version_url: str = Field("", max_length=500)


class ReleaseTaskUpdate(WorkflowBaseModel):
    status: Optional[ReleaseStatus] = None
    server_deploy_result: Optional[str] = Field(None, max_length=2000)
    mini_program_test_result: Optional[str] = Field(None, max_length=2000)
    version: Optional[str] = Field(None, max_length=80)
    release_notes: Optional[str] = Field(None, max_length=2000)
    rollback_notes: Optional[str] = Field(None, max_length=2000)
    release_checklist: Optional[str] = Field(None, max_length=3000)
    risk_notes: Optional[str] = Field(None, max_length=3000)
    known_issues: Optional[str] = Field(None, max_length=3000)
    test_version_url: Optional[str] = Field(None, max_length=500)
    acceptance_status: Optional[AcceptanceStatus] = None
    acceptance_notes: Optional[str] = Field(None, max_length=2000)
    acceptance_blocker_notes: Optional[str] = Field(None, max_length=2000)


class ReleaseTaskOut(ReleaseTaskCreate):
    id: str
    status: ReleaseStatus
    server_deploy_result: str
    mini_program_test_result: str
    version: str
    release_notes: str
    rollback_notes: str
    release_checklist: str
    risk_notes: str
    known_issues: str
    test_version_url: str
    created_at: str
    updated_at: str


class AcceptanceUpdate(WorkflowBaseModel):
    status: AcceptanceStatus
    notes: str = Field("", max_length=2000)
    blocker_notes: str = Field("", max_length=2000)


class AcceptanceOut(WorkflowBaseModel):
    id: str
    release_task_id: str
    status: AcceptanceStatus
    notes: str
    blocker_notes: str
    created_at: str
    updated_at: str


class WorkflowBoardOut(BaseModel):
    requirements: list[RequirementOut]
    development_tasks: list[DevelopmentTaskOut]
    test_tasks: list[TestTaskOut]
    release_tasks: list[ReleaseTaskOut]
    acceptances: list[AcceptanceOut]
    versions: list[str] = Field(default_factory=list)
    selected_version: str = ""
