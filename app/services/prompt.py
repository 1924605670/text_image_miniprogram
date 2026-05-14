from __future__ import annotations

from app.schemas import GenerationRequest, StylePreset


STYLE_PRESETS: dict[str, StylePreset] = {
    "none": StylePreset(id="none", label="原始", prompt_suffix=""),
    "cinematic": StylePreset(
        id="cinematic",
        label="电影感",
        prompt_suffix=(
            "cinematic lighting, carefully framed composition, rich atmosphere, "
            "natural depth, premium color grading"
        ),
    ),
    "product": StylePreset(
        id="product",
        label="产品",
        prompt_suffix=(
            "commercial product photography, clean studio lighting, crisp material detail, "
            "balanced reflections, premium catalog finish"
        ),
    ),
    "illustration": StylePreset(
        id="illustration",
        label="插画",
        prompt_suffix=(
            "high-end editorial illustration, expressive shapes, clean color harmony, "
            "confident linework, polished visual storytelling"
        ),
    ),
    "poster": StylePreset(
        id="poster",
        label="海报",
        prompt_suffix=(
            "poster-ready composition, strong focal point, dramatic hierarchy, "
            "memorable silhouette, print-quality finish"
        ),
    ),
    "architecture": StylePreset(
        id="architecture",
        label="建筑",
        prompt_suffix=(
            "architectural visualization, realistic spatial proportions, material accuracy, "
            "soft daylight, refined environmental context"
        ),
    ),
}


def compose_prompt(request: GenerationRequest) -> str:
    parts = [request.prompt]
    preset = STYLE_PRESETS.get(request.style_preset, STYLE_PRESETS["none"])

    if preset.prompt_suffix:
        parts.append(f"Style direction: {preset.prompt_suffix}.")

    if request.negative_prompt:
        parts.append(f"Avoid: {request.negative_prompt}.")

    parts.append(
        "Ensure the image is coherent, visually polished, and faithful to the requested subject."
    )
    return "\n\n".join(part for part in parts if part.strip())


def style_options() -> list[dict[str, str]]:
    return [
        {"id": preset.id, "label": preset.label}
        for preset in STYLE_PRESETS.values()
    ]

