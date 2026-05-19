from __future__ import annotations

from app.workflow_schemas import (
    AcceptanceUpdate,
    DEFAULT_RELEASE_CHECKLIST,
    DevelopmentTaskCreate,
    DevelopmentTaskUpdate,
    ReleaseTaskCreate,
    ReleaseTaskUpdate,
    RequirementCreate,
    TestTaskCreate,
    TestTaskUpdate,
    WorkflowBoardOut,
)
from app.services.workflow_store import WorkflowStore


class WorkflowRuleError(ValueError):
    pass


class WorkflowService:
    def __init__(self, store: WorkflowStore) -> None:
        self.store = store

    def board(self, version: str = "") -> WorkflowBoardOut:
        requirements = self.store.list_requirements()
        development_tasks = self.store.list_development_tasks()
        test_tasks = self.store.list_test_tasks()
        release_tasks = self.store.list_release_tasks()
        acceptances = self.store.list_acceptances()
        versions = _versions(requirements, release_tasks)
        selected_version = version.strip()

        if selected_version:
            requirements, development_tasks, test_tasks, release_tasks, acceptances = _filter_board(
                selected_version,
                requirements,
                development_tasks,
                test_tasks,
                release_tasks,
                acceptances,
            )

        return WorkflowBoardOut(
            requirements=requirements,
            development_tasks=development_tasks,
            test_tasks=test_tasks,
            release_tasks=release_tasks,
            acceptances=acceptances,
            versions=versions,
            selected_version=selected_version,
        )

    def create_requirement(self, request: RequirementCreate) -> dict:
        return self.store.create_requirement(request.model_dump())

    def confirm_requirement(self, requirement_id: str) -> dict:
        requirement = self.store.get_requirement(requirement_id)
        if not requirement["acceptance_criteria"].strip():
            raise WorkflowRuleError("未填写验收标准的需求不能确认")
        return self.store.update_requirement(requirement_id, status="confirmed")

    def pause_requirement(self, requirement_id: str) -> dict:
        return self.store.update_requirement(requirement_id, status="paused")

    def create_development_task(self, request: DevelopmentTaskCreate) -> dict:
        requirement = self.store.get_requirement(request.requirement_id)
        if requirement["status"] != "confirmed":
            raise WorkflowRuleError("未确认的需求不能进入开发")
        return self.store.create_development_task(request.model_dump())

    def update_development_task(self, task_id: str, request: DevelopmentTaskUpdate) -> dict:
        current = self.store.get_development_task(task_id)
        fields = request.model_dump(exclude_none=True)
        next_status = fields.get("status", current["status"])
        next_self_test = fields.get("self_test_notes", current.get("self_test_notes", ""))
        if next_status == "submitted_to_test" and not next_self_test.strip():
            raise WorkflowRuleError("未填写自测说明的开发任务不能提交测试")
        return self.store.update_development_task(task_id, **fields)

    def create_test_task(self, request: TestTaskCreate) -> dict:
        development_task = self.store.get_development_task(request.development_task_id)
        if development_task["status"] != "submitted_to_test":
            raise WorkflowRuleError("开发任务提交测试后才能创建测试任务")
        data = request.model_dump()
        data["requirement_id"] = development_task["requirement_id"]
        return self.store.create_test_task(data)

    def update_test_task(self, task_id: str, request: TestTaskUpdate) -> dict:
        current = self.store.get_test_task(task_id)
        fields = request.model_dump(exclude_none=True)
        next_status = fields.get("status", current["status"])
        defect_notes = fields.get("defect_notes", current.get("defect_notes", ""))
        result_notes = fields.get("result_notes", current.get("result_notes", ""))
        if next_status == "failed" and not defect_notes.strip():
            raise WorkflowRuleError("测试失败必须记录缺陷说明")
        if next_status == "passed" and not result_notes.strip():
            raise WorkflowRuleError("测试通过必须记录测试结果")
        task = self.store.update_test_task(task_id, **fields)
        if next_status == "failed":
            self.store.update_development_task(task["development_task_id"], status="in_progress")
        return task

    def create_release_task(self, request: ReleaseTaskCreate) -> dict:
        test_task = self.store.get_test_task(request.test_task_id)
        if test_task["status"] != "passed":
            raise WorkflowRuleError("未测试通过的功能不能进入发布任务")
        data = request.model_dump()
        if not data.get("release_checklist", "").strip():
            data["release_checklist"] = DEFAULT_RELEASE_CHECKLIST
        return self.store.create_release_task(data)

    def update_release_task(self, task_id: str, request: ReleaseTaskUpdate) -> dict:
        current = self.store.get_release_task(task_id)
        fields = request.model_dump(exclude_none=True)
        acceptance_status = fields.pop("acceptance_status", None)
        acceptance_notes = fields.pop("acceptance_notes", "")
        acceptance_blocker_notes = fields.pop("acceptance_blocker_notes", "")
        is_submitting_test_version = (
            fields.get("status") == "submitted_test_version"
            and current["status"] != "submitted_test_version"
        )
        server_result = fields.get("server_deploy_result", current.get("server_deploy_result", ""))
        mini_result = fields.get("mini_program_test_result", current.get("mini_program_test_result", ""))
        release_checklist = fields.get("release_checklist", current.get("release_checklist", ""))
        if is_submitting_test_version and (
            not server_result.strip() or not mini_result.strip()
        ):
            raise WorkflowRuleError("提交测试版前必须记录服务器部署结果和小程序测试版本提交结果")
        if is_submitting_test_version and not _checklist_complete(release_checklist):
            raise WorkflowRuleError("提交测试版前必须完成发布检查清单")
        release = self.store.update_release_task(task_id, **fields)
        if release["status"] == "submitted_test_version":
            self.store.upsert_acceptance(task_id, status="pending", notes="")
        if acceptance_status is not None:
            self.update_acceptance(
                task_id,
                AcceptanceUpdate(
                    status=acceptance_status,
                    notes=acceptance_notes,
                    blocker_notes=acceptance_blocker_notes,
                ),
            )
        return release

    def update_acceptance(self, release_task_id: str, request: AcceptanceUpdate) -> dict:
        release = self.store.get_release_task(release_task_id)
        if release["status"] != "submitted_test_version":
            raise WorkflowRuleError("小程序测试版提交成功后才能验收")
        if request.status == "rejected" and not request.blocker_notes.strip():
            raise WorkflowRuleError("验收驳回必须记录阻塞原因")
        return self.store.upsert_acceptance(
            release_task_id,
            status=request.status,
            notes=request.notes,
            blocker_notes=request.blocker_notes,
        )


def _versions(requirements: list[dict], release_tasks: list[dict]) -> list[str]:
    seen = {
        item.get("expected_version", "").strip()
        for item in requirements
        if item.get("expected_version", "").strip()
    }
    seen.update(
        item.get("version", "").strip()
        for item in release_tasks
        if item.get("version", "").strip()
    )
    return sorted(seen, reverse=True)


def _filter_board(
    version: str,
    requirements: list[dict],
    development_tasks: list[dict],
    test_tasks: list[dict],
    release_tasks: list[dict],
    acceptances: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    test_by_id = {item["id"]: item for item in test_tasks}
    selected_requirement_ids = {
        item["id"]
        for item in requirements
        if item.get("expected_version", "").strip() == version
    }
    selected_release_ids = {
        item["id"]
        for item in release_tasks
        if item.get("version", "").strip() == version
    }
    selected_test_ids = {
        release["test_task_id"]
        for release in release_tasks
        if release["id"] in selected_release_ids
    }
    selected_test_ids.update(
        item["id"]
        for item in test_tasks
        if item.get("requirement_id") in selected_requirement_ids
    )
    selected_development_ids = {
        test_by_id[test_id]["development_task_id"]
        for test_id in selected_test_ids
        if test_id in test_by_id
    }
    selected_development_ids.update(
        item["id"]
        for item in development_tasks
        if item.get("requirement_id") in selected_requirement_ids
    )
    selected_requirement_ids.update(
        item["requirement_id"]
        for item in development_tasks
        if item["id"] in selected_development_ids
    )
    selected_test_ids.update(
        item["id"]
        for item in test_tasks
        if item.get("development_task_id") in selected_development_ids
    )
    selected_release_ids.update(
        item["id"]
        for item in release_tasks
        if item.get("test_task_id") in selected_test_ids and item.get("version", "").strip() == version
    )
    selected_acceptance_release_ids = selected_release_ids

    return (
        [item for item in requirements if item["id"] in selected_requirement_ids],
        [item for item in development_tasks if item["id"] in selected_development_ids],
        [item for item in test_tasks if item["id"] in selected_test_ids],
        [item for item in release_tasks if item["id"] in selected_release_ids],
        [item for item in acceptances if item["release_task_id"] in selected_acceptance_release_ids],
    )


def _checklist_complete(value: str) -> bool:
    lines = [line.strip().lower() for line in value.splitlines() if line.strip()]
    checkbox_lines = [line for line in lines if line.startswith("- [")]
    if not checkbox_lines:
        return bool(value.strip())
    return all(line.startswith("- [x]") for line in checkbox_lines)
