from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings
from app.schemas import PromptOptimizeRequest, ToutiaoPackageOut, ToutiaoPackageRequest


class PromptOptimizeError(RuntimeError):
    pass


class ToutiaoPackageError(RuntimeError):
    pass


@dataclass
class OptimizeResult:
    optimized_prompt: str


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def optimize_prompt(self, req: PromptOptimizeRequest) -> OptimizeResult:
        if not self.settings.has_api_key:
            raise PromptOptimizeError("IMAGE_API_KEY is missing")

        payload = self._payload(req)

        content = await self._post_chat_with_fallback(
            payload,
            "llm optimize failed",
            PromptOptimizeError,
        )
        if not content:
            raise PromptOptimizeError("llm optimize returned empty content")
        return OptimizeResult(optimized_prompt=content)

    async def generate_toutiao_package(self, req: ToutiaoPackageRequest) -> ToutiaoPackageOut:
        if not self.settings.has_api_key:
            raise ToutiaoPackageError("IMAGE_API_KEY is missing")

        try:
            content = await self._post_chat_with_fallback(
                self._toutiao_payload(req),
                "llm toutiao package failed",
                ToutiaoPackageError,
            )
            data = _extract_json_object(content)
            return ToutiaoPackageOut.model_validate(data)
        except Exception as exc:
            if isinstance(exc, ToutiaoPackageError):
                return _fallback_toutiao_package(req, str(exc))
            return _fallback_toutiao_package(req, "llm toutiao package returned invalid structure")

    async def _post_chat_with_fallback(
        self,
        payload: dict[str, Any],
        error_prefix: str,
        error_cls: type[RuntimeError],
    ) -> str:
        failures: list[str] = []
        for model in _candidate_llm_models(self.settings):
            model_payload = {**payload, "model": model}
            try:
                content = await self._post_chat(model_payload, error_prefix, error_cls)
            except error_cls as exc:
                failures.append(f"{model}: {exc}")
                continue
            if content:
                return content
            failures.append(f"{model}: empty content")
        raise error_cls(_all_model_failures_message(error_prefix, failures))

    async def _post_chat(
        self,
        payload: dict[str, Any],
        error_prefix: str,
        error_cls: type[RuntimeError],
    ) -> str:
        timeout = httpx.Timeout(min(self.settings.request_timeout_seconds, 180.0), connect=20.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.post(
                    self.settings.chat_completions_url,
                    json=payload,
                    headers=self._headers(),
                )
            except httpx.TimeoutException as exc:
                raise error_cls(f"{error_prefix}: provider request timed out") from exc
            except httpx.HTTPError as exc:
                raise error_cls(f"{error_prefix}: provider request failed: {exc}") from exc
            if resp.status_code >= 400:
                raise error_cls(_response_error_message(resp, prefix=error_prefix))

        return _extract_response_content(resp, error_prefix, error_cls)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, req: PromptOptimizeRequest) -> dict[str, Any]:
        return {
            "model": self.settings.llm_model,
            "max_tokens": 600,
            "messages": [
                {"role": "system", "content": _system_instruction()},
                {"role": "user", "content": _user_brief(req)},
            ],
        }

    def _toutiao_payload(self, req: ToutiaoPackageRequest) -> dict[str, Any]:
        max_tokens = {
            "short": 900,
            "standard": 1800,
            "long": 3000,
        }[req.length]
        return {
            "model": self.settings.llm_model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": _toutiao_system_instruction()},
                {"role": "user", "content": _toutiao_user_brief(req)},
            ],
        }


def _system_instruction() -> str:
    return (
        "You are an expert GPT-Image-2 prompt engineer. "
        "Rewrite user input into a production-ready image prompt. "
        "Keep original intent, language, and key entities. "
        "Use a structured creative-brief style with concrete visual details.\n\n"
        "Output rules:\n"
        "1) Return plain prompt text only, no headings, no markdown, no quotes.\n"
        "2) Include: scene, subject, composition, lens/view, lighting, material/texture, mood, style cues, and quality constraints.\n"
        "3) If user requests text-in-image, preserve exact quoted text faithfully.\n"
        "4) Avoid contradictions and unsafe content.\n"
        "5) Do not mention output size, aspect ratio, file format, or literal quality setting; those are controlled by UI parameters.\n"
        "6) Keep within ~80-220 Chinese characters when user writes Chinese; otherwise ~60-180 English words."
    )


def _user_brief(req: PromptOptimizeRequest) -> str:
    return (
        f"User prompt: {req.prompt.strip()}\n"
        f"Style preset: {req.style_preset}\n"
        f"Target size: {req.size}\n"
        f"Quality: {req.quality}\n"
        f"Output format: {req.output_format}\n"
        "Use these UI parameters as context, but keep them out of the optimized prompt text."
    )


def _toutiao_system_instruction() -> str:
    return (
        "你是今日头条图文内容产品的资深编辑和封面图策划。"
        "根据用户提供的事实材料，生成适合头条图文发布的中文内容包。"
        "必须遵守：不编造未提供的事实、数据、身份、地点和时间；不做标题党；"
        "不使用震惊、速看、全网炸了等夸张诱导；标题和封面必须与正文事实一致；"
        "涉及不确定信息时写入 fact_check_notes，不要把未经确认的推断写成事实；"
        "避免医疗、金融、法律等高风险确定性建议；封面图不要出现真实媒体 Logo、平台 Logo、"
        "公众人物肖像或容易误导为现场新闻照片的画面。\n\n"
        "只输出一个合法 JSON 对象，不要 markdown，不要代码块。字段："
        "best_title:string，title_options:string[3-5]，lead:string，body:string，"
        "summary_bullets:string[3-5]，cover_brief:string，image_prompt:string，"
        "image_negative_prompt:string，compliance_notes:string[3-6]，fact_check_notes:string[0-5]。"
    )


def _toutiao_user_brief(req: ToutiaoPackageRequest) -> str:
    length_hint = {
        "short": "约350-500字，适合快讯和短图文。",
        "standard": "约700-1000字，适合常规头条图文。",
        "long": "约1200-1600字，适合深度解读。",
    }[req.length]
    style_hint = {
        "news": "资讯报道：倒金字塔结构，先给结论和关键信息。",
        "analysis": "解读分析：解释背景、影响和后续观察点。",
        "local": "本地民生：贴近日常生活，语气稳健。",
        "technology": "科技数码：突出功能变化、用户场景和限制条件。",
        "consumer": "消费服务：强调选择建议、注意事项和适用人群。",
        "story": "故事叙述：有人物和情境，但不得虚构事实。",
    }[req.article_style]
    cover_hint = {
        "realistic": "真实摄影感但不伪造新闻现场，干净自然光。",
        "editorial": "新闻编辑部风格，信息感强，适合封面。",
        "tech": "科技感、产品感、清晰界面元素。",
        "local": "城市和生活场景，朴素可信。",
        "data": "数据可视化和信息图风格，不包含具体虚构数字。",
    }[req.cover_style]
    return (
        f"选题：{req.topic}\n"
        f"事实材料：{req.facts}\n"
        f"报道角度：{req.angle or '由你基于事实材料选择最稳妥角度'}\n"
        f"目标读者：{req.audience}\n"
        f"文章类型：{style_hint}\n"
        f"篇幅：{length_hint}\n"
        f"封面风格：{cover_hint}\n\n"
        "生成要求：\n"
        "1. best_title 控制在 16-28 个中文字符左右，信息明确，不夸张。\n"
        "2. title_options 给出不同角度标题，避免重复句式。\n"
        "3. body 使用短段落，适合手机阅读；如材料不足，明确提醒还需补充事实。\n"
        "4. image_prompt 直接可用于文生图，描述主体、场景、构图、光线、风格和质量约束；"
        "不要要求图片里出现大量中文文字。\n"
        "5. compliance_notes 写明本内容如何避免标题党、事实夸大和封面误导。"
    )


def _extract_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
    if isinstance(msg, dict):
        content = msg.get("content")
        parsed = _content_value(content)
        if parsed:
            return parsed
    return ""


def _extract_response_content(
    response: httpx.Response,
    error_prefix: str,
    error_cls: type[RuntimeError],
) -> str:
    content_type = response.headers.get("content-type", "")
    text = response.text
    if "text/event-stream" in content_type or text.lstrip().startswith("data:"):
        try:
            return _extract_stream_content(text)
        except ValueError as exc:
            raise error_cls(_response_invalid_json_message(response, prefix=error_prefix)) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise error_cls(_response_invalid_json_message(response, prefix=error_prefix)) from exc
    if not isinstance(data, dict):
        raise error_cls(f"{error_prefix}: provider returned non-object JSON")
    return _extract_content(data)


def _extract_stream_content(text: str) -> str:
    parts: list[str] = []
    for data in _iter_sse_data(text):
        data = data.strip()
        if not data or data == "[DONE]":
            continue
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ValueError("provider returned invalid streaming JSON") from exc
        if not isinstance(parsed, dict):
            continue
        top_level = _content_value(parsed.get("content") or parsed.get("output_text"))
        if top_level:
            parts.append(top_level)
        choices = parsed.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            for key in ("delta", "message"):
                node = choice.get(key)
                if not isinstance(node, dict):
                    continue
                content = _content_value(node.get("content"))
                if content:
                    parts.append(content)
            text_value = _content_value(choice.get("text"))
            if text_value:
                parts.append(text_value)
    return "".join(parts).strip()


def _iter_sse_data(text: str) -> list[str]:
    data_items: list[str] = []
    data_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            if data_lines:
                data_items.append("\n".join(data_lines))
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        data_items.append("\n".join(data_lines))
    return data_items


def _content_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "".join(parts).strip()


def _extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise ToutiaoPackageError("llm toutiao package returned non-json content")
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ToutiaoPackageError("llm toutiao package returned non-object JSON")
    return parsed


def _fallback_toutiao_package(req: ToutiaoPackageRequest, reason: str) -> ToutiaoPackageOut:
    topic = _trim_sentence(req.topic, 42)
    facts = _trim_sentence(req.facts, 420)
    angle = _angle_clause(req.angle)
    audience = req.audience or "今日头条普通读者"
    fact_sentences = _split_fact_sentences(req.facts)
    bullets = [_trim_sentence(item, 80) for item in fact_sentences[:3]]
    if len(bullets) < 3:
        bullets.append(_trim_sentence(f"报道角度聚焦：{angle}", 80))
    if len(bullets) < 3:
        bullets.append("发布前建议补充明确来源、时间、地点和责任方。")

    title_seed = _trim_sentence(topic, 22)
    best_title = _trim_sentence(f"{title_seed}带来哪些新变化", 32)
    title_options = [
        best_title,
        _trim_sentence(f"{title_seed}这些进展值得关注", 32),
        _trim_sentence(f"围绕{title_seed}读者关心这几点", 32),
    ]

    lead = _trim_sentence(
        f"围绕{topic}，现有材料显示：{fact_sentences[0] if fact_sentences else facts}",
        220,
    )
    body = (
        f"围绕{topic}，现有材料显示：{facts}\n\n"
        f"{angle}看，这一选题适合先交代已经发生的变化，再说明对{audience}的直接影响。"
        "写作时应把确定事实、用户反馈和后续计划分开表达，避免把尚未落地的安排写成结果。\n\n"
        "后续发布前，建议继续补充具体时间、地点、责任方或公开来源。"
        "如果材料暂时不足，正文应使用'据现有材料'、'后续仍需观察'等稳健表述。"
    )
    cover_brief = _trim_sentence(
        f"围绕{topic}制作新闻图文封面，突出与事实材料一致的真实生活或行业场景。",
        260,
    )
    image_prompt = _trim_sentence(
        "Editorial Chinese news cover image, realistic but not a live breaking-news photo, "
        f"topic: {topic}, based only on these provided facts: {_strip_terminal_punctuation(facts)}. "
        "Clean mobile-first composition, natural light, credible everyday scene, no text overlays, "
        "no logos, no public figures, no sensational atmosphere.",
        1100,
    )
    return ToutiaoPackageOut(
        best_title=best_title,
        title_options=title_options,
        lead=lead,
        body=body,
        summary_bullets=bullets[:5],
        cover_brief=cover_brief,
        image_prompt=image_prompt,
        image_negative_prompt=(
            "No text, no platform logo, no media logo, no celebrity, no public figure, "
            "no fake disaster scene, no exaggerated emotion, no misleading live-news framing."
        ),
        compliance_notes=[
            "已使用保守模板兜底，仅围绕用户提供的事实材料组织内容。",
            "标题避免夸张诱导表达，正文区分事实、反馈和后续计划。",
            "封面提示词不要求出现真实媒体标识、公众人物或伪现场新闻画面。",
        ],
        fact_check_notes=[
            "模型服务响应不稳定，本稿为保守草稿，发布前建议人工复核。",
            _trim_sentence(f"兜底原因：{reason}", 120),
            "如需更强新闻稿质量，建议补充明确来源、时间、地点、数据口径和采访对象。",
        ],
    )


def _split_fact_sentences(text: str) -> list[str]:
    normalized = text.replace("\n", " ").strip()
    parts = [
        item.strip(" ，,。；;")
        for item in normalized.replace("；", "。").replace(";", "。").split("。")
        if item.strip(" ，,。；;")
    ]
    return parts or ([normalized] if normalized else [])


def _angle_clause(value: str) -> str:
    compact = _strip_terminal_punctuation(" ".join(value.split()).strip())
    if not compact:
        return "从读者最关心的变化和影响切入"
    if compact.startswith("从"):
        return compact
    return f"从{compact}"


def _strip_terminal_punctuation(value: str) -> str:
    return value.rstrip("。.!！?？；;，, ")


def _trim_sentence(value: str, max_length: int) -> str:
    compact = " ".join(value.split()).strip()
    if len(compact) <= max_length:
        return compact
    if max_length <= 1:
        return compact[:max_length]
    return f"{compact[: max_length - 1].rstrip()}…"


def _response_error_message(response: httpx.Response, *, prefix: str = "llm optimize failed") -> str:
    try:
        parsed = response.json()
    except ValueError:
        body = response.text.strip()
    else:
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(error, dict) and error.get("message"):
            body = str(error["message"]).strip()
        elif isinstance(parsed, dict) and parsed.get("message"):
            body = str(parsed["message"]).strip()
        else:
            body = ""
    return f"{prefix}: HTTP {response.status_code}: {body or response.reason_phrase}"


def _response_invalid_json_message(response: httpx.Response, *, prefix: str = "llm optimize failed") -> str:
    body = _response_text_snippet(response)
    return f"{prefix}: HTTP {response.status_code}: provider returned invalid JSON: {body}"


def _response_text_snippet(response: httpx.Response, max_length: int = 220) -> str:
    text = response.text.strip()
    if not text:
        return "<empty response body>"
    text = " ".join(text.split())
    if len(text) <= max_length:
        return text
    return f"{text[:max_length].rstrip()}..."


def _candidate_llm_models(settings: Settings) -> list[str]:
    configured = [settings.llm_model, *getattr(settings, "llm_fallback_models", ())]
    models: list[str] = []
    for model in configured:
        value = str(model).strip()
        if value and value not in models:
            models.append(value)
    return models


def _all_model_failures_message(error_prefix: str, failures: list[str]) -> str:
    if not failures:
        return f"{error_prefix}: no configured LLM model"
    details = "; ".join(_truncate_failure(item) for item in failures[:4])
    if len(failures) > 4:
        details = f"{details}; ..."
    return f"{error_prefix}: all configured LLM models failed: {details}"


def _truncate_failure(value: str, max_length: int = 180) -> str:
    compact = " ".join(value.split())
    if len(compact) <= max_length:
        return compact
    return f"{compact[:max_length].rstrip()}..."
