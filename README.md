# Text Image Demo

一期目标：一个本地可运行的文生图工作台，后端保存密钥并调用 `gpt-image-2`，前端只和本地 API 通信。

## 一期功能

- 文生图任务：提示词、负面提示词、风格预设、尺寸、质量、格式、压缩率、背景、生成张数。
- 小程序测试版工作台：需求池、开发自测、测试记录、发布记录和产品验收看板。
- 二期版本验收工作台：版本筛选、发布检查清单、风险/遗留问题、测试入口和验收阻塞记录。
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
- `GET /api/workflow/board`：小程序测试版流程看板。
- `GET /api/workflow/board?version=0.2.0`：按版本筛选流程看板，并返回可选版本列表。
- `POST /api/workflow/requirements`：创建需求。
- `POST /api/workflow/requirements/{requirement_id}/confirm`：确认需求。
- `POST /api/workflow/development-tasks`：创建开发任务。
- `PATCH /api/workflow/development-tasks/{task_id}`：更新开发任务状态和自测说明。
- `POST /api/workflow/test-tasks`：创建测试任务。
- `PATCH /api/workflow/test-tasks/{task_id}`：更新测试结果。
- `POST /api/workflow/release-tasks`：创建发布任务。
- `PATCH /api/workflow/release-tasks/{task_id}`：更新发布记录。
- `PATCH /api/workflow/release-tasks/{task_id}/acceptance`：产品验收。

## 小程序测试版发布

本仓库当前没有微信小程序工程目录、appid、上传私钥或 `miniprogram-ci` 脚本，所以本次迭代已完成应用内测试版发布记录与验收流，尚不能真实上传到微信测试版本。产品、设计、技术和测试规划见 `docs/mini-program-product-iteration.md`。

## 后台服务部署记录

小程序后台服务在 `111.229.10.122`，可通过免密 SSH 登录：

```bash
ssh ubuntu@111.229.10.122
```

线上服务信息：

- 服务目录：`/home/ubuntu/apps/text_image_backend`
- 监听地址：`127.0.0.1:18090`
- 启动命令：`.venv/bin/python3 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 18090`
- 运行日志：`/home/ubuntu/apps/text_image_backend/app.log`
- 配置和数据：保留远端 `.env.local`、`data/`、`generated/`、`references/`，不要从本地覆盖
- 同机还有其他服务，不要使用 `pkill uvicorn`、`killall python`、重启整机等粗暴操作

部署原则：远端后台包含本地仓库没有的登录、额度、参考图、提示词优化等接口，不能整目录覆盖。只同步本次需要更新的文件，并且重启前必须确认 PID 的 cwd 是 `/home/ubuntu/apps/text_image_backend`。

更新前备份：

```bash
ssh ubuntu@111.229.10.122 'cd /home/ubuntu/apps/text_image_backend && ts=$(date +%Y%m%d%H%M%S) && mkdir -p backups/deploy-$ts && cp app/main.py app/config.py app/schemas.py backups/deploy-$ts/ && echo backups/deploy-$ts'
```

同步本次 workflow 后台文件示例：

```bash
scp app/workflow_schemas.py ubuntu@111.229.10.122:/home/ubuntu/apps/text_image_backend/app/workflow_schemas.py
scp app/services/workflow_store.py app/services/workflow_service.py ubuntu@111.229.10.122:/home/ubuntu/apps/text_image_backend/app/services/
```

如果需要更新远端 `app/main.py`，先从服务器拉取远端版本，在本地临时文件里合并增量，再传回，避免覆盖远端已有接口：

```bash
scp ubuntu@111.229.10.122:/home/ubuntu/apps/text_image_backend/app/main.py /tmp/text_image_backend_main.py
# 在 /tmp/text_image_backend_main.py 合并改动并本地检查后再上传
python3 -m py_compile /tmp/text_image_backend_main.py
scp /tmp/text_image_backend_main.py ubuntu@111.229.10.122:/home/ubuntu/apps/text_image_backend/app/main.py
```

远端预检：

```bash
ssh ubuntu@111.229.10.122 'cd /home/ubuntu/apps/text_image_backend && .venv/bin/python -m compileall app && .venv/bin/python -c "import app.main; print(\"import ok\")"'
```

只重启目标后台服务：

```bash
ssh ubuntu@111.229.10.122 'bash -s' <<'REMOTE'
set -euo pipefail
APP_DIR=/home/ubuntu/apps/text_image_backend
PORT=18090
cd "$APP_DIR"
old_pid=$(ss -ltnp 2>/dev/null | grep ":$PORT" | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -1 || true)
if [ -n "${old_pid:-}" ]; then
  old_cwd=$(readlink "/proc/$old_pid/cwd" 2>/dev/null || true)
  if [ "$old_cwd" != "$APP_DIR" ]; then
    echo "Refusing to stop pid $old_pid with cwd=$old_cwd"
    exit 1
  fi
  kill "$old_pid"
  for _ in $(seq 1 30); do
    if ! kill -0 "$old_pid" 2>/dev/null; then break; fi
    sleep 0.5
  done
fi
nohup .venv/bin/python3 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" >> app.log 2>&1 < /dev/null &
sleep 2
curl -fsS "http://127.0.0.1:$PORT/api/health" >/tmp/text_image_health.json
REMOTE
```

部署后验证：

```bash
ssh ubuntu@111.229.10.122 'curl -fsS http://127.0.0.1:18090/api/health | head -c 300; echo'
ssh ubuntu@111.229.10.122 'curl -fsS http://127.0.0.1:18090/api/workflow/board; echo'
ssh ubuntu@111.229.10.122 'curl -fsS -X POST http://127.0.0.1:18090/api/auth/login -H "Content-Type: application/json" -d "{\"client_user_id\":\"u_deploy_check_20260520\"}" | head -c 300; echo'
```

2026-05-20 更新记录：

- 备份：`/home/ubuntu/apps/text_image_backend/backups/workflow-20260520005858`、`/home/ubuntu/apps/text_image_backend/backups/config-wechat-20260520010733`
- 增量新增：`app/workflow_schemas.py`、`app/services/workflow_store.py`、`app/services/workflow_service.py`
- 增量更新：远端 `app/main.py` 新增 `/api/workflow/*` 接口；远端 `app/config.py` 补充 `WECHAT_APP_ID`、`WECHAT_APP_SECRET` 默认字段，修复 client login 因配置字段缺失导致的 500
- 重启后 PID：`468166`
- 验证通过：`/api/health`、`/api/workflow/board`、`POST /api/auth/login`

二期开发说明：

- `workflow_release_tasks` 新增发布检查清单、风险记录、遗留问题和测试入口字段。
- `workflow_acceptances` 新增验收阻塞原因字段。
- SQLite 会在服务启动时自动补列，适配服务器已有数据库。
- 提交测试版前必须记录服务器部署结果、小程序测试版提交结果，并完成发布检查清单。
- 验收驳回必须记录阻塞原因。
- 2026-05-20 二期版本验收工作台已通过 CI/CD 同步到服务器，备份：`/home/ubuntu/apps/text_image_backend/backups/cicd-20260520024906`，验证通过：`/`、`/api/health`、`/api/workflow/board?version=0.2.0`。
- 同次部署发现 CI/CD 在重启阶段存在端口释放竞态，已更新 `scripts/deploy_backend.sh`：增加 `.deploy.lock` 部署锁，停止旧进程后等待 `18090` 端口真正释放，再启动并轮询健康检查。修复验证备份：`/home/ubuntu/apps/text_image_backend/backups/cicd-20260520025406`。

## GitHub CI/CD

目标仓库：

```bash
git@github.com:1924605670/text_image_miniprogram.git
```

本项目已添加 GitHub Actions 工作流：`.github/workflows/backend-ci-cd.yml`。流程为：

1. push 到 `main` 或 `master` 后安装依赖并运行 `pytest -q`。
2. 测试通过后执行 `scripts/deploy_backend.sh`。
3. 部署脚本通过 SSH 登录服务器，备份当前后台代码，用 `rsync --delete` 同步仓库代码。
4. 同步时保留远端 `.env.local`、`data/`、`generated/`、`references/`、`.venv/`、`backups/` 和 `app.log`。
5. 远端安装依赖、编译检查、import 检查，然后只重启 `127.0.0.1:18090` 对应且 cwd 为 `/home/ubuntu/apps/text_image_backend` 的目标服务。
6. 最后验证 `/api/health` 和 `/api/workflow/board`。

GitHub 仓库需要配置 Actions Secrets：

- `DEPLOY_HOST`：`111.229.10.122`
- `DEPLOY_SSH_KEY`：专用 CI 部署私钥内容

本机已生成一把专用 CI 部署 key，并已加入服务器 `ubuntu` 用户的 `authorized_keys`：

```bash
cat ~/.ssh/text_image_miniprogram_ci_ed25519
```

把上面命令输出的完整私钥内容填入 GitHub 仓库的 `DEPLOY_SSH_KEY` secret。

首次推送仓库：

```bash
git remote add origin git@github.com:1924605670/text_image_miniprogram.git
git branch -M main
git push -u origin main
```

如果 GitHub SSH 22 端口不可用，可以使用 443 端口 remote：

```bash
git remote set-url origin ssh://git@ssh.github.com:443/1924605670/text_image_miniprogram.git
```

注意：当前机器上的 GitHub SSH key 可能没有该仓库权限。验证命令：

```bash
ssh -T -p 443 git@ssh.github.com
git ls-remote ssh://git@ssh.github.com:443/1924605670/text_image_miniprogram.git
```

## 后续方向

- 前端展示流式 partial image 预览。
- 图片编辑和参考图上传。
- 多用户隔离、登录、配额与审计。
- 任务取消、并发限制、持久化 worker。
- Prompt 模板库和常用尺寸模板。
