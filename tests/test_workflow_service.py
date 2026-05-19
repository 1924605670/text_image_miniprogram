import pytest
from pydantic import ValidationError

from app.services.workflow_service import WorkflowRuleError, WorkflowService
from app.services.workflow_store import WorkflowStore
from app.workflow_schemas import (
    AcceptanceUpdate,
    DevelopmentTaskCreate,
    DevelopmentTaskUpdate,
    ReleaseTaskCreate,
    ReleaseTaskUpdate,
    RequirementCreate,
    TestTaskCreate as WorkflowTestTaskCreate,
    TestTaskUpdate as WorkflowTestTaskUpdate,
)


def test_requirement_create_strips_text_fields() -> None:
    requirement = RequirementCreate(
        title="  需求标题  ",
        background="  背景说明  ",
        business_goal="  业务目标  ",
        scope="  功能范围  ",
        acceptance_criteria="  验收标准  ",
        expected_version="  v1.0.0  ",
    )

    assert requirement.title == "需求标题"
    assert requirement.background == "背景说明"
    assert requirement.business_goal == "业务目标"
    assert requirement.scope == "功能范围"
    assert requirement.acceptance_criteria == "验收标准"
    assert requirement.expected_version == "v1.0.0"


def test_requirement_create_requires_acceptance_criteria() -> None:
    with pytest.raises(ValidationError):
        RequirementCreate(
            title="需求标题",
            business_goal="业务目标",
            scope="功能范围",
            acceptance_criteria="   ",
        )


def test_workflow_blocks_unconfirmed_requirement_from_development(tmp_path) -> None:
    service = WorkflowService(WorkflowStore(tmp_path / "app.db"))
    requirement = service.create_requirement(
        RequirementCreate(
            title="图片编辑能力",
            business_goal="提升图片返工效率",
            scope="支持基于历史图片再次编辑",
            acceptance_criteria="可以从历史记录发起编辑并得到新图",
        )
    )

    with pytest.raises(WorkflowRuleError, match="未确认"):
        service.create_development_task(
            DevelopmentTaskCreate(
                requirement_id=requirement["id"],
                title="编辑入口",
                description="在历史记录增加编辑入口",
                developer="dev",
            )
        )


def test_development_submit_requires_self_test_notes(tmp_path) -> None:
    service = WorkflowService(WorkflowStore(tmp_path / "app.db"))
    requirement = _confirmed_requirement(service)
    task = service.create_development_task(
        DevelopmentTaskCreate(
            requirement_id=requirement["id"],
            title="发布流",
            description="实现开发任务状态流转",
            developer="dev",
        )
    )

    with pytest.raises(WorkflowRuleError, match="自测说明"):
        service.update_development_task(task["id"], DevelopmentTaskUpdate(status="submitted_to_test"))


def test_release_and_acceptance_require_test_version_submission(tmp_path) -> None:
    service = WorkflowService(WorkflowStore(tmp_path / "app.db"))
    requirement = _confirmed_requirement(service)
    development = service.create_development_task(
        DevelopmentTaskCreate(
            requirement_id=requirement["id"],
            title="测试版发布",
            description="实现发布记录",
            developer="dev",
        )
    )
    service.update_development_task(
        development["id"],
        DevelopmentTaskUpdate(
            status="submitted_to_test",
            self_test_notes="自测主流程和异常提示通过",
        ),
    )
    test_task = service.create_test_task(
        WorkflowTestTaskCreate(
            development_task_id=development["id"],
            test_cases="需求确认、开发提交、测试通过、发布、验收",
            tester="qa",
        )
    )
    service.update_test_task(
        test_task["id"],
        WorkflowTestTaskUpdate(status="passed", result_notes="回归通过"),
    )
    release = service.create_release_task(
        ReleaseTaskCreate(
            test_task_id=test_task["id"],
            operator="ops",
            version="0.2.0-test",
            release_notes="提交小程序测试版记录",
            rollback_notes="回退上一测试版本",
        )
    )

    with pytest.raises(WorkflowRuleError, match="测试版提交成功"):
        service.update_acceptance(release["id"], AcceptanceUpdate(status="accepted", notes="通过"))

    with pytest.raises(WorkflowRuleError, match="服务器部署结果"):
        service.update_release_task(release["id"], ReleaseTaskUpdate(status="submitted_test_version"))

    service.update_release_task(
        release["id"],
        ReleaseTaskUpdate(
            status="submitted_test_version",
            server_deploy_result="服务健康检查通过",
            mini_program_test_result="小程序测试版提交成功",
        ),
    )
    acceptance = service.update_acceptance(
        release["id"],
        AcceptanceUpdate(status="accepted", notes="产品验收通过"),
    )

    assert acceptance["status"] == "accepted"


def _confirmed_requirement(service: WorkflowService) -> dict:
    requirement = service.create_requirement(
        RequirementCreate(
            title="小程序测试版协作流",
            business_goal="让产品、开发、测试、运维能围绕版本闭环",
            scope="需求、开发、自测、测试、发布、验收",
            acceptance_criteria="测试版提交成功后产品可以验收",
            expected_version="0.2.0",
        )
    )
    return service.confirm_requirement(requirement["id"])
