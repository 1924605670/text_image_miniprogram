# Text Image Demo

一期目标：一个本地可运行的文生图工作台，后端保存密钥并调用 `gpt-image-2`，前端只和本地 API 通信。

## 一期功能

- 文生图任务：提示词、负面提示词、风格预设、尺寸、质量、格式、压缩率、背景、生成张数。
- 后端任务队列：创建任务后异步执行，前端轮询状态。
- 重试机制：网络异常、超时、429、5xx 等可恢复错误会指数退避重试。
- 长耗时处理：默认使用 Image API 流式生成，避免代理长时间无响应导致 504。
- 图片落盘：生成结果保存到 `generated/`，历史记录保存到 SQLite。
- 历史记录：查看最近任务、失败原因、重试同一任务。
- 配置隔离：密钥在 `.env`，不会下发到浏览器。
- 基础测试：提示词组合、参数校验、重试判定、SQLite 记录。

## 运行

```bash
cd /Volumes/MacData/projects/text_image_demo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000`。

## 测试

```bash
source .venv/bin/activate
pytest
```

## API

- `GET /api/health`：运行状态和脱敏配置。
- `GET /api/options`：前端选项。
- `POST /api/generations`：创建生成任务。
- `GET /api/generations`：任务历史。
- `GET /api/generations/{job_id}`：任务详情。
- `POST /api/generations/{job_id}/retry`：用同一参数重新创建任务。
- `GET /api/images/{filename}`：读取本地生成图片。

## 后续方向

- 前端展示流式 partial image 预览。
- 图片编辑和参考图上传。
- 多用户隔离、登录、配额与审计。
- 任务取消、并发限制、持久化 worker。
- Prompt 模板库和常用尺寸模板。
