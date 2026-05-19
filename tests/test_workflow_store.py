from pathlib import Path

from app.services.workflow_store import WorkflowStore


def test_workflow_store_roundtrip(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "app.db")
    requirement = store.create_requirement(
        {
            "title": "需求",
            "background": "背景",
            "business_goal": "目标",
            "priority": "high",
            "scope": "范围",
            "acceptance_criteria": "验收",
            "expected_version": "0.2.0",
        }
    )
    updated = store.update_requirement(requirement["id"], status="confirmed")

    assert updated["status"] == "confirmed"
    assert store.get_requirement(requirement["id"])["title"] == "需求"
    assert len(store.list_requirements()) == 1


def test_workflow_store_keeps_relationships(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "app.db")
    requirement = store.create_requirement(
        {
            "title": "需求",
            "background": "",
            "business_goal": "目标",
            "priority": "medium",
            "scope": "范围",
            "acceptance_criteria": "验收",
            "expected_version": "",
        }
    )
    development = store.create_development_task(
        {
            "requirement_id": requirement["id"],
            "title": "开发任务",
            "description": "实现功能",
            "developer": "dev",
        }
    )
    test_task = store.create_test_task(
        {
            "development_task_id": development["id"],
            "requirement_id": requirement["id"],
            "test_cases": "主流程",
            "tester": "qa",
        }
    )
    release = store.create_release_task(
        {
            "test_task_id": test_task["id"],
            "operator": "ops",
            "version": "test",
            "release_notes": "提交测试版",
            "rollback_notes": "回退上一版",
        }
    )
    acceptance = store.upsert_acceptance(release["id"], status="pending")

    assert development["requirement_id"] == requirement["id"]
    assert test_task["requirement_id"] == requirement["id"]
    assert acceptance["release_task_id"] == release["id"]
