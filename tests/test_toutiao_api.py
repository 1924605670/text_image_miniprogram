from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
from app.schemas import ToutiaoPackageOut
from app.services.storage import JobStore


class FakeLLMClient:
    async def generate_toutiao_package(self, request):
        return ToutiaoPackageOut(
            best_title="新能源补贴调整，车主需要关注这些变化",
            title_options=[
                "新能源补贴调整，车主需要关注这些变化",
                "补贴范围有变化，申请前先看这几项",
                "一地更新新能源补贴政策，影响哪些人",
            ],
            lead="某地新能源补贴政策出现调整，申请范围和条件是读者最需要先了解的信息。",
            body="第一段说明事实。\n\n第二段解释影响。",
            summary_bullets=["补贴范围调整", "申请条件变化", "建议以官方口径为准"],
            cover_brief="新能源车和政策文件的编辑部封面",
            image_prompt="新闻编辑部风格封面，新能源车停在城市道路旁，旁边有抽象政策文件元素。",
            image_negative_prompt="不要真实 Logo，不要夸张文字",
            compliance_notes=["标题不夸张", "封面不伪造现场", "事实来自用户材料"],
            fact_check_notes=["需补充政策发布时间"],
        )


def test_create_toutiao_package_without_image(tmp_path: Path) -> None:
    original_llm = main.llm_client
    original_store = main.store
    main.llm_client = FakeLLMClient()
    main.store = JobStore(tmp_path / "app.db")
    client = TestClient(main.app)
    try:
        response = client.post(
            "/api/toutiao-packages",
            json={
                "topic": "新能源补贴调整",
                "facts": "某地发布新政策，补贴范围和申请条件发生调整，具体细则以官方公告为准。",
                "include_image": False,
            },
        )
    finally:
        main.llm_client = original_llm
        main.store = original_store

    assert response.status_code == 201
    payload = response.json()
    assert payload["package"]["best_title"].startswith("新能源补贴")
    assert payload["package"]["image_prompt"]
    assert payload["image_job"] is None
