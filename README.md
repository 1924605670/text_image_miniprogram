# AI 文生图小程序

这个项目现在只做一件事：把文字提示词稳定生成图片。小程序端直接请求线上后台，后台保存密钥、创建图片任务、异步生成、保存结果和历史记录。

## 当前产品范围

- 小程序首页即文生图工作台，不做发布稿、流程看板或多业务入口。
- 支持提示词、负面提示词、风格、尺寸、质量设置。
- 支持提示词优化，一键使用优化后的提示词。
- 支持异步生成、状态轮询、图片预览、复制图片链接、失败重试。
- 支持最近任务查看和复用历史提示词。
- 后端对外只保留文生图、提示词优化、历史任务、参考图、登录配额和管理能力。

## 线上地址

小程序请求：

```text
https://api2.hometodo.top/wximg
```

常用接口：

- `GET /api/health`：运行状态和脱敏配置。
- `GET /api/options`：文生图选项。
- `POST /api/prompt-optimize`：优化提示词。
- `POST /api/generations`：创建图片生成任务。
- `GET /api/generations`：最近任务。
- `GET /api/generations/{job_id}`：任务详情。
- `POST /api/generations/{job_id}/retry`：重试任务。
- `GET /api/images/{filename}`：读取生成图片。

## 本地开发

```bash
cd /Volumes/MacData/projects/text_image_demo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000` 可调试 Web 后台。小程序默认不请求本地 8000，而是请求线上域名。

## 测试

```bash
source .venv/bin/activate
pytest -q
python -m compileall app
node -c miniprogram/pages/index/index.js
```

## 微信小程序

- 工程目录：`miniprogram/`
- AppID：`wx30321379334ec662`
- 根配置：`project.config.json`
- 基础库固定：`3.14.2`，避免 `latest` 带来的开发者工具内部 SDK 波动

打开项目：

```bash
/Applications/wechatwebdevtools.app/Contents/MacOS/cli open --project /Volumes/MacData/projects/text_image_demo --lang zh
```

上传测试版示例：

```bash
/Applications/wechatwebdevtools.app/Contents/MacOS/cli upload \
  --project /Volumes/MacData/projects/text_image_demo \
  --version 0.4.0 \
  --desc '聚焦 AI 文生图体验' \
  --lang zh
```

如果开发者工具中遇到 request 合法域名限制，需要在微信公众平台后台把 `https://api2.hometodo.top` 加入 request 合法域名；开发阶段也可以在工具里勾选“不校验合法域名”。

## 后台部署

服务器：`111.229.10.122`

```bash
ssh ubuntu@111.229.10.122
```

线上服务信息：

- 服务目录：`/home/ubuntu/apps/text_image_backend`
- 监听地址：`127.0.0.1:18090`
- 启动命令：`.venv/bin/python3 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 18090`
- 运行日志：`/home/ubuntu/apps/text_image_backend/app.log`
- 保留远端 `.env.local`、`data/`、`generated/`、`references/`、`.venv/`、`backups/` 和 `app.log`
- 同机还有其他服务，不要使用 `pkill uvicorn`、`killall python`、重启整机等粗暴操作

CI/CD 已配置到 GitHub Actions。push 到 `master` 后会运行测试，成功后通过 `scripts/deploy_backend.sh` 同步到服务器，并只重启 `127.0.0.1:18090` 且 cwd 为 `/home/ubuntu/apps/text_image_backend` 的目标进程。

目标仓库：

```bash
git@github.com:1924605670/text_image_miniprogram.git
```

必要 GitHub Secrets：

- `DEPLOY_HOST`：`111.229.10.122`
- `DEPLOY_SSH_KEY`：专用 CI 部署私钥内容

部署后验证：

```bash
curl -fsS https://api2.hometodo.top/wximg/api/health
curl -fsS https://api2.hometodo.top/wximg/api/generations?limit=3
```

## 产品原则

- 唯一主线是文生图，不再把发布稿、流程管理、测试验收作为小程序入口。
- 默认设置要能直接出图，高级设置只服务于更可控的图片质量。
- 历史任务必须可复用，失败任务必须可重试。
- 图片结果优先展示图片，其次才是最终提示词和日志。
