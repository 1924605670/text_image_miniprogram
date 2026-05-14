from app.schemas import GenerationRequest
from app.services.prompt import compose_prompt


def test_compose_prompt_includes_style_and_negative_prompt() -> None:
    request = GenerationRequest(
        prompt="一辆红色跑车停在雨夜街头",
        negative_prompt="模糊, 变形文字",
        style_preset="cinematic",
    )

    final_prompt = compose_prompt(request)

    assert "一辆红色跑车停在雨夜街头" in final_prompt
    assert "cinematic lighting" in final_prompt
    assert "Avoid: 模糊, 变形文字." in final_prompt


def test_unknown_style_falls_back_to_plain_prompt() -> None:
    request = GenerationRequest(prompt="未来城市", style_preset="missing")

    final_prompt = compose_prompt(request)

    assert "未来城市" in final_prompt
    assert "Style direction" not in final_prompt

