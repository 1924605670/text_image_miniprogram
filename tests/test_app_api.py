from fastapi.testclient import TestClient

from app.main import app


def test_root_serves_image_only_workbench() -> None:
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "AI 文生图" in response.text
    assert "workflow" not in response.text.lower()
    assert "toutiao" not in response.text.lower()


def test_removed_legacy_product_apis_are_not_exposed() -> None:
    client = TestClient(app)

    assert client.get("/api/workflow/board").status_code == 404
    assert client.post(
        "/api/toutiao-packages",
        json={"topic": "旧功能", "facts": "旧功能不再作为产品能力。"},
    ).status_code == 404
