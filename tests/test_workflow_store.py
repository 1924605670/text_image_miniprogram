import sqlite3
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


def test_workflow_store_phase_two_fields_roundtrip(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "app.db")
    requirement = store.create_requirement(
        {
            "title": "需求",
            "background": "",
            "business_goal": "目标",
            "priority": "medium",
            "scope": "范围",
            "acceptance_criteria": "验收",
            "expected_version": "0.2.0",
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
            "version": "0.2.0-test",
            "release_notes": "提交测试版",
            "rollback_notes": "回退上一版",
            "release_checklist": "- [x] 服务健康检查通过",
            "risk_notes": "微信后台配置待确认",
            "known_issues": "体验版二维码暂未自动回填",
            "test_version_url": "https://example.test/version",
        }
    )
    acceptance = store.upsert_acceptance(
        release["id"],
        status="rejected",
        notes="未通过",
        blocker_notes="发现阻塞问题",
    )

    assert release["release_checklist"] == "- [x] 服务健康检查通过"
    assert release["risk_notes"] == "微信后台配置待确认"
    assert release["known_issues"] == "体验版二维码暂未自动回填"
    assert release["test_version_url"] == "https://example.test/version"
    assert acceptance["blocker_notes"] == "发现阻塞问题"


def test_workflow_store_backfills_empty_release_checklist(tmp_path: Path) -> None:
    database = tmp_path / "app.db"
    store = WorkflowStore(database)
    requirement = store.create_requirement(
        {
            "title": "需求",
            "background": "",
            "business_goal": "目标",
            "priority": "medium",
            "scope": "范围",
            "acceptance_criteria": "验收",
            "expected_version": "0.2.0",
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
            "version": "0.2.0-test",
            "release_notes": "提交测试版",
            "rollback_notes": "回退上一版",
            "release_checklist": "",
        }
    )

    assert release["release_checklist"]


def test_workflow_store_backfills_submitted_release_checklist_as_done(tmp_path: Path) -> None:
    database = tmp_path / "app.db"
    store = WorkflowStore(database)
    requirement = store.create_requirement(
        {
            "title": "需求",
            "background": "",
            "business_goal": "目标",
            "priority": "medium",
            "scope": "范围",
            "acceptance_criteria": "验收",
            "expected_version": "0.2.0",
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
            "version": "0.2.0-test",
            "release_notes": "提交测试版",
            "rollback_notes": "回退上一版",
            "release_checklist": "",
        }
    )
    store.update_release_task(release["id"], status="submitted_test_version")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE workflow_release_tasks SET release_checklist = '' WHERE id = ?",
            (release["id"],),
        )

    migrated = WorkflowStore(database)
    release_after_migration = migrated.get_release_task(release["id"])

    assert "- [x]" in release_after_migration["release_checklist"]
