from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
from app.services.workflow_service import WorkflowService
from app.services.workflow_store import WorkflowStore


def test_workflow_api_happy_path(tmp_path: Path) -> None:
    main.workflow_service = WorkflowService(WorkflowStore(tmp_path / "app.db"))
    client = TestClient(main.app)

    requirement = client.post(
        "/api/workflow/requirements",
        json={
            "title": "小程序测试版协作流",
            "business_goal": "形成产品到验收闭环",
            "scope": "需求、开发、测试、发布、验收",
            "acceptance_criteria": "提交测试版后可以产品验收",
            "expected_version": "0.2.0",
        },
    )
    assert requirement.status_code == 201
    requirement_id = requirement.json()["id"]
    assert client.post(f"/api/workflow/requirements/{requirement_id}/confirm").status_code == 200

    development = client.post(
        "/api/workflow/development-tasks",
        json={
            "requirement_id": requirement_id,
            "title": "实现协作看板",
            "description": "补齐状态流转",
            "developer": "dev",
        },
    )
    assert development.status_code == 201
    development_id = development.json()["id"]
    assert (
        client.patch(
            f"/api/workflow/development-tasks/{development_id}",
            json={
                "status": "submitted_to_test",
                "self_test_notes": "主流程和异常规则通过",
            },
        ).status_code
        == 200
    )

    test_task = client.post(
        "/api/workflow/test-tasks",
        json={
            "development_task_id": development_id,
            "test_cases": "全链路流转",
            "tester": "qa",
        },
    )
    assert test_task.status_code == 201
    test_id = test_task.json()["id"]
    assert (
        client.patch(
            f"/api/workflow/test-tasks/{test_id}",
            json={"status": "passed", "result_notes": "回归通过"},
        ).status_code
        == 200
    )

    release = client.post(
        "/api/workflow/release-tasks",
        json={
            "test_task_id": test_id,
            "operator": "ops",
            "version": "0.2.0-test",
            "release_notes": "提交测试版",
            "rollback_notes": "回退上一测试版本",
        },
    )
    assert release.status_code == 201
    release_id = release.json()["id"]
    assert (
        client.patch(
            f"/api/workflow/release-tasks/{release_id}",
            json={
                "status": "submitted_test_version",
                "server_deploy_result": "服务健康检查通过",
                "mini_program_test_result": "测试版提交成功",
                "release_checklist": (
                    "- [x] 服务器部署健康检查通过\n"
                    "- [x] 小程序测试版提交记录完整\n"
                    "- [x] 回滚方案和负责人已确认"
                ),
                "risk_notes": "微信测试版上传仍需人工确认",
                "known_issues": "暂无阻塞遗留",
            },
        ).status_code
        == 200
    )
    accepted = client.patch(
        f"/api/workflow/release-tasks/{release_id}/acceptance",
        json={"status": "accepted", "notes": "产品验收通过"},
    )

    assert accepted.status_code == 200
    board = client.get("/api/workflow/board")
    assert board.status_code == 200
    assert board.json()["acceptances"][0]["status"] == "accepted"
    assert "0.2.0" in board.json()["versions"]

    filtered = client.get("/api/workflow/board?version=0.2.0")
    assert filtered.status_code == 200
    assert filtered.json()["selected_version"] == "0.2.0"
    assert filtered.json()["requirements"][0]["id"] == requirement_id


def test_root_serves_workbench() -> None:
    client = TestClient(main.app)
    response = client.get("/")

    assert response.status_code == 200
    assert "小程序测试版工作台" in response.text
