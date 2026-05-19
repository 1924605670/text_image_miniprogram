from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from app import main


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_reference_upload_base64_saves_detected_png(tmp_path) -> None:
    old_reference_dir = main.settings.reference_dir
    object.__setattr__(main.settings, "reference_dir", tmp_path)
    try:
        client = TestClient(main.app)

        response = client.post(
            "/api/reference-images/base64",
            json={
                "image_base64": base64.b64encode(PNG_BYTES).decode("ascii"),
                "filename": "wx_tmp_upload",
                "content_type": "application/octet-stream",
            },
        )

        assert response.status_code == 201
        filename = response.json()["filename"]
        assert filename.endswith(".png")
        assert (tmp_path / filename).read_bytes() == PNG_BYTES
    finally:
        object.__setattr__(main.settings, "reference_dir", old_reference_dir)


def test_reference_from_generated_copies_output_image(tmp_path) -> None:
    old_output_dir = main.settings.output_dir
    old_reference_dir = main.settings.reference_dir
    output_dir = tmp_path / "generated"
    reference_dir = tmp_path / "references"
    output_dir.mkdir()
    reference_dir.mkdir()
    source = output_dir / "job-1.png"
    source.write_bytes(PNG_BYTES)
    object.__setattr__(main.settings, "output_dir", output_dir)
    object.__setattr__(main.settings, "reference_dir", reference_dir)
    try:
        client = TestClient(main.app)

        response = client.post(
            "/api/reference-images/from-generated",
            json={"filename": "job-1.png"},
        )

        assert response.status_code == 201
        filename = response.json()["filename"]
        assert filename.endswith(".png")
        assert (reference_dir / filename).read_bytes() == PNG_BYTES
    finally:
        object.__setattr__(main.settings, "output_dir", old_output_dir)
        object.__setattr__(main.settings, "reference_dir", old_reference_dir)
