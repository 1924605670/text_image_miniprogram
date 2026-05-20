from __future__ import annotations

import base64
import binascii
import re
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.schemas import (
    AdminStatsOut,
    AuthLoginRequest,
    AuthLoginResponse,
    CreateGenerationResponse,
    GenerationRequest,
    ImageAsset,
    JobOut,
    PromptOptimizeRequest,
    PromptOptimizeResponse,
    ReferenceFromGeneratedRequest,
    ReferenceUploadBase64Request,
    ReferenceUploadResponse,
    ToutiaoPackageRequest,
    ToutiaoPackageResponse,
    UserOut,
    UserQuotaUpdateRequest,
)
from app.services.generation_service import GenerationService
from app.services.image_client import ImageClient, normalize_provider_error_message
from app.services.llm_client import LLMClient, PromptOptimizeError, ToutiaoPackageError
from app.services.prompt import style_options
from app.services.storage import JobStore, QuotaExceededError
from app.services.workflow_service import WorkflowRuleError, WorkflowService
from app.services.workflow_store import WorkflowStore
from app.workflow_schemas import (
    AcceptanceOut,
    AcceptanceUpdate,
    DevelopmentTaskCreate,
    DevelopmentTaskOut,
    DevelopmentTaskUpdate,
    ReleaseTaskCreate,
    ReleaseTaskOut,
    ReleaseTaskUpdate,
    RequirementCreate,
    RequirementOut,
    TestTaskCreate,
    TestTaskOut,
    TestTaskUpdate,
    WorkflowBoardOut,
)


app = FastAPI(title="Text Image MiniProgram Backend", version="0.1.0")
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

store = JobStore(settings.database_path)
workflow_store = WorkflowStore(settings.database_path)
generation_service = GenerationService(settings=settings, store=store, client=ImageClient(settings))
workflow_service = WorkflowService(workflow_store)
llm_client = LLMClient(settings)

ALLOWED_REFERENCE_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/heic",
    "image/heif",
    "application/octet-stream",
}
ALLOWED_REFERENCE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"}
REFERENCE_SUFFIX_BY_CONTENT_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
}
MAX_REFERENCE_IMAGE_BYTES = 20 * 1024 * 1024


@app.get("/", response_class=HTMLResponse)
async def index_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": {
            "base_url": settings.api_base_url,
            "generation_url": settings.generation_url,
            "edit_url": settings.edit_url,
            "llm_url": settings.chat_completions_url,
            "image_model": settings.model,
            "llm_model": settings.llm_model,
            "llm_fallback_models": list(settings.llm_fallback_models),
            "api_key": settings.masked_api_key,
            "has_api_key": settings.has_api_key,
            "backup_base_url": settings.backup_api_base_url,
            "backup_generation_url": (
                settings.backup_generation_url if settings.backup_api_base_url else ""
            ),
            "backup_api_key": settings.backup_masked_api_key,
            "backup_has_api_key": settings.backup_has_api_key,
        },
        "storage": {
            "database": str(settings.database_path),
            "output_dir": str(settings.output_dir),
            "reference_dir": str(settings.reference_dir),
        },
        "admin": {
            "token_enabled": bool(settings.admin_token),
        },
        "retry": {
            "attempts": settings.retry_attempts,
            "base_delay_seconds": settings.retry_base_delay_seconds,
            "timeout_seconds": settings.request_timeout_seconds,
            "streaming": settings.use_streaming,
            "partial_images": settings.partial_images,
        },
    }


@app.get("/api/options")
async def options() -> dict[str, Any]:
    return {
        "styles": style_options(),
        "sizes": [
            {"value": "1024x1024", "label": "1:1 1024"},
            {"value": "1536x1024", "label": "3:2 1536x1024"},
            {"value": "1024x1536", "label": "2:3 1024x1536"},
            {"value": "2048x2048", "label": "2K 1:1"},
            {"value": "2048x1152", "label": "2K 16:9"},
            {"value": "3840x2160", "label": "4K 16:9"},
            {"value": "2160x3840", "label": "4K 9:16"},
            {"value": "auto", "label": "自动"},
        ],
        "qualities": ["auto", "low", "medium", "high"],
        "formats": ["png", "jpeg", "webp"],
        "backgrounds": ["auto", "opaque"],
    }


@app.post("/api/auth/login", response_model=AuthLoginResponse)
async def auth_login(request: AuthLoginRequest) -> AuthLoginResponse:
    user_id = request.client_user_id or ""
    login_type = "client"
    if settings.wechat_app_id and settings.wechat_app_secret and request.code:
        openid = await _wechat_openid(request.code)
        user_id = f"wx_{openid}"
        login_type = "wechat"
    if not user_id:
        raise HTTPException(status_code=400, detail="missing user id")
    clean_user_id = _clean_user_id(user_id)
    user = store.ensure_user(clean_user_id)
    return AuthLoginResponse(user_id=clean_user_id, login_type=login_type, user=UserOut(**user))


@app.post("/api/prompt-optimize", response_model=PromptOptimizeResponse)
async def optimize_prompt(request: PromptOptimizeRequest) -> PromptOptimizeResponse:
    try:
        result = await llm_client.optimize_prompt(request)
    except PromptOptimizeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PromptOptimizeResponse(optimized_prompt=result.optimized_prompt)


@app.post("/api/toutiao-packages", response_model=ToutiaoPackageResponse, status_code=201)
async def create_toutiao_package(request: ToutiaoPackageRequest) -> ToutiaoPackageResponse:
    try:
        package = await llm_client.generate_toutiao_package(request)
    except ToutiaoPackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    image_job = None
    if request.include_image:
        try:
            image_job = generation_service.create_generation(
                GenerationRequest(
                    prompt=package.image_prompt,
                    negative_prompt=package.image_negative_prompt,
                    style_preset="editorial",
                    size="2048x1152",
                    quality="high",
                    output_format="png",
                    background="auto",
                    n=1,
                    client_user_id=request.client_user_id,
                )
            )
        except QuotaExceededError as exc:
            raise HTTPException(status_code=402, detail="使用次数不足，请联系管理员增加次数") from exc
    return ToutiaoPackageResponse(
        package=package,
        image_job=_job_out(image_job) if image_job else None,
    )


@app.post("/api/reference-images", response_model=ReferenceUploadResponse, status_code=201)
async def upload_reference_image(file: UploadFile = File(...)) -> ReferenceUploadResponse:
    content = await file.read()
    return _save_reference_image(
        content=content,
        content_type=file.content_type,
        original_filename=file.filename,
    )


@app.post("/api/reference-images/base64", response_model=ReferenceUploadResponse, status_code=201)
async def upload_reference_image_base64(request: ReferenceUploadBase64Request) -> ReferenceUploadResponse:
    return _save_reference_image(
        content=_decode_reference_image_base64(request.image_base64),
        content_type=request.content_type,
        original_filename=request.filename,
    )


@app.post("/api/reference-images/from-generated", response_model=ReferenceUploadResponse, status_code=201)
async def create_reference_from_generated(request: ReferenceFromGeneratedRequest) -> ReferenceUploadResponse:
    clean_name = Path(request.filename).name
    if clean_name != request.filename:
        raise HTTPException(status_code=400, detail="invalid filename")

    source = settings.output_dir / clean_name
    if not source.exists():
        raise HTTPException(status_code=404, detail="image not found")

    return _save_reference_image(
        content=source.read_bytes(),
        content_type=None,
        original_filename=clean_name,
    )


@app.post("/api/generations", response_model=CreateGenerationResponse, status_code=202)
async def create_generation(request: GenerationRequest) -> CreateGenerationResponse:
    try:
        job = generation_service.create_generation(request)
    except QuotaExceededError as exc:
        raise HTTPException(status_code=402, detail="使用次数不足，请联系管理员增加次数") from exc
    return CreateGenerationResponse(job=_job_out(job))


@app.get("/api/generations", response_model=list[JobOut])
async def list_generations(limit: int = 30) -> list[JobOut]:
    limit = max(1, min(limit, 100))
    return [_job_out(job) for job in store.list_jobs(limit=limit)]


@app.get("/api/generations/{job_id}", response_model=JobOut)
async def get_generation(job_id: str) -> JobOut:
    try:
        return _job_out(store.get_job(job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@app.get("/api/users/{user_id}/generations", response_model=list[JobOut])
async def list_user_generations(
    user_id: str,
    limit: int = 50,
    status: Optional[str] = None,
) -> list[JobOut]:
    clean_user_id = _clean_user_id(user_id)
    limit = max(1, min(limit, 100))
    if status and status not in {"pending", "running", "succeeded", "failed"}:
        raise HTTPException(status_code=400, detail="invalid status")
    return [
        _job_out(job)
        for job in store.list_jobs_by_user(clean_user_id, limit=limit, status=status)
    ]


@app.post("/api/generations/{job_id}/retry", response_model=CreateGenerationResponse, status_code=202)
async def retry_generation(job_id: str) -> CreateGenerationResponse:
    try:
        job = generation_service.retry_generation(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    except QuotaExceededError as exc:
        raise HTTPException(status_code=402, detail="使用次数不足，请联系管理员增加次数") from exc
    return CreateGenerationResponse(job=_job_out(job))



@app.get("/api/workflow/board", response_model=WorkflowBoardOut)
async def workflow_board(version: str = "") -> WorkflowBoardOut:
    return workflow_service.board(version=version)


@app.post("/api/workflow/requirements", response_model=RequirementOut, status_code=201)
async def create_requirement(request: RequirementCreate) -> RequirementOut:
    return RequirementOut.model_validate(workflow_service.create_requirement(request))


@app.post("/api/workflow/requirements/{requirement_id}/confirm", response_model=RequirementOut)
async def confirm_requirement(requirement_id: str) -> RequirementOut:
    try:
        return RequirementOut.model_validate(workflow_service.confirm_requirement(requirement_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="requirement not found") from exc
    except WorkflowRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workflow/requirements/{requirement_id}/pause", response_model=RequirementOut)
async def pause_requirement(requirement_id: str) -> RequirementOut:
    try:
        return RequirementOut.model_validate(workflow_service.pause_requirement(requirement_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="requirement not found") from exc


@app.post("/api/workflow/development-tasks", response_model=DevelopmentTaskOut, status_code=201)
async def create_development_task(request: DevelopmentTaskCreate) -> DevelopmentTaskOut:
    try:
        return DevelopmentTaskOut.model_validate(workflow_service.create_development_task(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="requirement not found") from exc
    except WorkflowRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/workflow/development-tasks/{task_id}", response_model=DevelopmentTaskOut)
async def update_development_task(
    task_id: str,
    request: DevelopmentTaskUpdate,
) -> DevelopmentTaskOut:
    try:
        return DevelopmentTaskOut.model_validate(workflow_service.update_development_task(task_id, request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="development task not found") from exc
    except WorkflowRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workflow/test-tasks", response_model=TestTaskOut, status_code=201)
async def create_test_task(request: TestTaskCreate) -> TestTaskOut:
    try:
        return TestTaskOut.model_validate(workflow_service.create_test_task(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="development task not found") from exc
    except WorkflowRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/workflow/test-tasks/{task_id}", response_model=TestTaskOut)
async def update_test_task(task_id: str, request: TestTaskUpdate) -> TestTaskOut:
    try:
        return TestTaskOut.model_validate(workflow_service.update_test_task(task_id, request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="test task not found") from exc
    except WorkflowRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workflow/release-tasks", response_model=ReleaseTaskOut, status_code=201)
async def create_release_task(request: ReleaseTaskCreate) -> ReleaseTaskOut:
    try:
        return ReleaseTaskOut.model_validate(workflow_service.create_release_task(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="test task not found") from exc
    except WorkflowRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/workflow/release-tasks/{task_id}", response_model=ReleaseTaskOut)
async def update_release_task(task_id: str, request: ReleaseTaskUpdate) -> ReleaseTaskOut:
    try:
        return ReleaseTaskOut.model_validate(workflow_service.update_release_task(task_id, request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release task not found") from exc
    except WorkflowRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/workflow/release-tasks/{task_id}/acceptance", response_model=AcceptanceOut)
async def update_acceptance(task_id: str, request: AcceptanceUpdate) -> AcceptanceOut:
    try:
        return AcceptanceOut.model_validate(workflow_service.update_acceptance(task_id, request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release task not found") from exc
    except WorkflowRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/users/{user_id}/stats", response_model=UserOut)
async def get_user_stats(user_id: str) -> UserOut:
    return UserOut(**store.user_stats(_clean_user_id(user_id)))


@app.get("/api/admin/stats", response_model=AdminStatsOut)
async def admin_stats(x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token")) -> AdminStatsOut:
    _require_admin_token(x_admin_token)
    return AdminStatsOut(**store.admin_stats())


@app.get("/api/admin/users", response_model=list[UserOut])
async def admin_users(
    limit: int = 100,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> list[UserOut]:
    _require_admin_token(x_admin_token)
    limit = max(1, min(limit, 500))
    return [UserOut(**user) for user in store.list_users(limit=limit)]


@app.patch("/api/admin/users/{user_id}", response_model=UserOut)
async def admin_update_user(
    user_id: str,
    request: UserQuotaUpdateRequest,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> UserOut:
    _require_admin_token(x_admin_token)
    return UserOut(**store.update_user_quota(
        _clean_user_id(user_id),
        quota_total=request.quota_total,
        quota_used=request.quota_used,
        note=request.note,
    ))


@app.get("/admin", response_class=HTMLResponse)
async def admin_page() -> HTMLResponse:
    return HTMLResponse(_admin_html())


@app.get("/api/images/{filename}")
async def read_image(filename: str) -> FileResponse:
    return _image_file_response(settings.output_dir, filename, "image not found")


@app.head("/api/images/{filename}")
async def head_image(filename: str) -> FileResponse:
    return _image_file_response(settings.output_dir, filename, "image not found")


@app.get("/api/reference-images/{filename}")
async def read_reference_image(filename: str) -> FileResponse:
    return _image_file_response(settings.reference_dir, filename, "reference image not found")


@app.head("/api/reference-images/{filename}")
async def head_reference_image(filename: str) -> FileResponse:
    return _image_file_response(settings.reference_dir, filename, "reference image not found")


def _image_file_response(directory: Path, filename: str, not_found: str) -> FileResponse:
    clean_name = Path(filename).name
    if clean_name != filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    path = directory / clean_name
    if not path.exists():
        raise HTTPException(status_code=404, detail=not_found)
    return FileResponse(
        path,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


def _job_out(record: dict[str, Any]) -> JobOut:
    images = [
        ImageAsset(
            filename=asset["filename"],
            url=f"{settings.image_base_url}/api/images/{asset['filename']}",
            revised_prompt=asset.get("revised_prompt"),
        )
        for asset in record.get("image_assets", [])
    ]
    return JobOut(
        id=record["id"],
        status=record["status"],
        prompt=record["prompt"],
        final_prompt=record["final_prompt"],
        request=record["request"],
        images=images,
        error=normalize_provider_error_message(record.get("error")),
        attempts=record.get("attempts") or 0,
        attempt_log=_clean_attempt_log(record.get("attempt_log") or []),
        model=record["model"],
        api_base_url=record["api_base_url"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        duration_ms=record.get("duration_ms"),
        parent_job_id=record.get("parent_job_id"),
        user_id=record.get("user_id"),
    )


def _clean_attempt_log(attempt_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for item in attempt_log:
        if not isinstance(item, dict):
            continue
        next_item = dict(item)
        next_item["message"] = normalize_provider_error_message(
            str(next_item.get("message") or ""),
            status_code=next_item.get("status_code"),
        )
        cleaned.append(next_item)
    return cleaned


def _save_reference_image(
    *,
    content: bytes,
    content_type: str | None,
    original_filename: str | None,
) -> ReferenceUploadResponse:
    if not content:
        raise HTTPException(status_code=400, detail="参考图不能为空")
    if len(content) > MAX_REFERENCE_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="参考图不能超过 20MB")

    suffix = _reference_image_suffix(
        content=content,
        content_type=content_type,
        original_filename=original_filename,
    )
    filename = f"ref-{uuid.uuid4().hex}{suffix}"
    target = settings.reference_dir / filename
    target.write_bytes(content)

    return ReferenceUploadResponse(
        filename=filename,
        url=f"{settings.image_base_url}/api/reference-images/{filename}",
    )


def _decode_reference_image_base64(value: str) -> bytes:
    payload = value.strip()
    if "," in payload and payload.lower().startswith("data:"):
        payload = payload.split(",", 1)[1]
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="参考图 base64 数据无效") from exc


def _reference_image_suffix(
    *,
    content: bytes,
    content_type: str | None,
    original_filename: str | None,
) -> str:
    detected_suffix = _detect_reference_image_suffix(content)
    if detected_suffix:
        return detected_suffix

    normalized_content_type = _normalize_content_type(content_type)
    suffix = Path(original_filename or "reference.png").suffix.lower()

    if suffix in ALLOWED_REFERENCE_SUFFIXES:
        return suffix
    if normalized_content_type in REFERENCE_SUFFIX_BY_CONTENT_TYPE:
        return REFERENCE_SUFFIX_BY_CONTENT_TYPE[normalized_content_type]
    if normalized_content_type in ALLOWED_REFERENCE_CONTENT_TYPES:
        return ".png"

    raise HTTPException(status_code=400, detail="只支持 png/jpeg/webp/heic 参考图")


def _normalize_content_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def _detect_reference_image_suffix(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    if len(content) >= 12 and content[4:8] == b"ftyp":
        brand = content[8:12]
        if brand in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}:
            return ".heic"
    return None


def _admin_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>文生图后台管理</title>
  <style>
    body { margin: 0; background: #f6f8fb; color: #0f172a; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    main { max-width: 1120px; margin: 0 auto; padding: 28px 18px 48px; }
    h1 { margin: 0 0 18px; font-size: 26px; }
    section { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 18px; margin-bottom: 16px; }
    input, button { height: 36px; border-radius: 8px; border: 1px solid #cbd5e1; padding: 0 10px; font-size: 14px; box-sizing: border-box; }
    button { cursor: pointer; color: #fff; background: #2563eb; border-color: #2563eb; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { border-bottom: 1px solid #e2e8f0; padding: 10px 8px; text-align: left; vertical-align: middle; }
    th { color: #475569; font-weight: 600; }
    .grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
    .metric { background: #f8fafc; border-radius: 8px; padding: 12px; }
    .label { color: #64748b; font-size: 12px; }
    .value { margin-top: 4px; font-size: 22px; font-weight: 700; }
    .token-row { display: flex; gap: 10px; align-items: center; }
    .token-row input { flex: 1; }
    .small-input { width: 86px; }
    .note-input { width: 150px; }
    .error { color: #b91c1c; margin-top: 10px; }
    @media (max-width: 760px) { .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } table { min-width: 880px; } .table-wrap { overflow-x: auto; } }
  </style>
</head>
<body>
<main>
  <h1>文生图后台管理</h1>
  <section>
    <div class="token-row">
      <input id="token" placeholder="输入 ADMIN_TOKEN" type="password" />
      <button onclick="loadData()">加载</button>
    </div>
    <div id="error" class="error"></div>
  </section>
  <section>
    <div class="grid" id="stats"></div>
  </section>
  <section>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>用户 ID</th><th>总次数</th><th>已用</th><th>剩余</th><th>任务</th><th>成功</th><th>失败</th><th>备注</th><th>操作</th>
          </tr>
        </thead>
        <tbody id="users"></tbody>
      </table>
    </div>
  </section>
</main>
<script>
const tokenInput = document.getElementById("token");
tokenInput.value = localStorage.getItem("admin_token") || "";

function headers() {
  const token = tokenInput.value.trim();
  localStorage.setItem("admin_token", token);
  return {"Content-Type": "application/json", "X-Admin-Token": token};
}

async function api(path, options = {}) {
  const res = await fetch(path, {...options, headers: {...headers(), ...(options.headers || {})}});
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try { message = (await res.json()).detail || message; } catch (_) {}
    throw new Error(message);
  }
  return res.json();
}

function setError(message) {
  document.getElementById("error").textContent = message || "";
}

function metric(label, value) {
  return `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div></div>`;
}

async function loadData() {
  setError("");
  try {
    const [stats, users] = await Promise.all([
      api("/api/admin/stats"),
      api("/api/admin/users?limit=200"),
    ]);
    document.getElementById("stats").innerHTML = [
      metric("用户数", stats.total_users),
      metric("任务数", stats.total_jobs),
      metric("成功", stats.succeeded_jobs),
      metric("运行中", stats.active_jobs),
      metric("总次数", stats.quota_total_sum),
      metric("已用", stats.quota_used_sum),
    ].join("");
    document.getElementById("users").innerHTML = users.map((user, index) => `
      <tr>
        <td>${user.id}</td>
        <td><input class="small-input" id="total-${index}" type="number" min="0" value="${user.quota_total}"></td>
        <td><input class="small-input" id="used-${index}" type="number" min="0" value="${user.quota_used}"></td>
        <td>${user.quota_remaining}</td>
        <td>${user.job_count}</td>
        <td>${user.succeeded_count}</td>
        <td>${user.failed_count}</td>
        <td><input class="note-input" id="note-${index}" value="${user.note || ""}"></td>
        <td><button onclick="saveUser('${user.id}', ${index})">保存</button></td>
      </tr>
    `).join("");
  } catch (err) {
    setError(err.message || "加载失败");
  }
}

async function saveUser(userId, index) {
  setError("");
  try {
    await api(`/api/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify({
        quota_total: Number(document.getElementById(`total-${index}`).value || 0),
        quota_used: Number(document.getElementById(`used-${index}`).value || 0),
        note: document.getElementById(`note-${index}`).value || "",
      }),
    });
    await loadData();
  } catch (err) {
    setError(err.message || "保存失败");
  }
}
</script>
</body>
</html>"""


def _clean_user_id(user_id: str) -> str:
    value = (user_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,80}", value):
        raise HTTPException(status_code=400, detail="invalid user id")
    return value


async def _wechat_openid(code: str) -> str:
    url = "https://api.weixin.qq.com/sns/jscode2session"
    params = {
        "appid": settings.wechat_app_id,
        "secret": settings.wechat_app_secret,
        "js_code": code,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
        response = await client.get(url, params=params)
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="wechat login returned invalid response") from exc
    if response.status_code >= 400 or data.get("errcode"):
        message = data.get("errmsg") if isinstance(data, dict) else None
        raise HTTPException(status_code=400, detail=f"wechat login failed: {message or response.status_code}")
    openid = str(data.get("openid") or "").strip()
    if not openid:
        raise HTTPException(status_code=400, detail="wechat login missing openid")
    return openid


def _require_admin_token(x_admin_token: Optional[str]) -> None:
    if settings.admin_token and x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="invalid admin token")
