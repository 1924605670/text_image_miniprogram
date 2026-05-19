#!/usr/bin/env bash
set -euo pipefail

DEPLOY_HOST="${DEPLOY_HOST:-111.229.10.122}"
DEPLOY_USER="${DEPLOY_USER:-ubuntu}"
APP_DIR="${APP_DIR:-/home/ubuntu/apps/text_image_backend}"
APP_PORT="${APP_PORT:-18090}"
REMOTE="${DEPLOY_USER}@${DEPLOY_HOST}"

echo "Deploying backend to ${REMOTE}:${APP_DIR}"

ssh "$REMOTE" "mkdir -p '$APP_DIR/backups'"
ssh "$REMOTE" "cd '$APP_DIR' && ts=\$(date +%Y%m%d%H%M%S) && mkdir -p backups/cicd-\$ts && cp -a app requirements.txt pyproject.toml .env.example backups/cicd-\$ts/ 2>/dev/null || true && echo backups/cicd-\$ts"

rsync -az --delete \
  --exclude '.git/' \
  --exclude '.github/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.env' \
  --exclude '.env.local' \
  --exclude 'data/' \
  --exclude 'generated/' \
  --exclude 'references/' \
  --exclude 'backups/' \
  --exclude 'app.log' \
  ./ "$REMOTE:$APP_DIR/"

ssh "$REMOTE" "bash -s" <<REMOTE
set -euo pipefail
APP_DIR="$APP_DIR"
APP_PORT="$APP_PORT"
cd "\$APP_DIR"

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m compileall app
.venv/bin/python -c "import app.main; print('import ok')"

old_pid=\$(ss -ltnp 2>/dev/null | grep ":\$APP_PORT" | sed -n 's/.*pid=\\([0-9][0-9]*\\).*/\\1/p' | head -1 || true)
if [ -n "\${old_pid:-}" ]; then
  old_cwd=\$(readlink "/proc/\$old_pid/cwd" 2>/dev/null || true)
  if [ "\$old_cwd" != "\$APP_DIR" ]; then
    echo "Refusing to stop pid \$old_pid with cwd=\$old_cwd"
    exit 1
  fi
  kill "\$old_pid"
  for _ in \$(seq 1 30); do
    if ! kill -0 "\$old_pid" 2>/dev/null; then
      break
    fi
    sleep 0.5
  done
  if kill -0 "\$old_pid" 2>/dev/null; then
    echo "pid \$old_pid did not stop in time"
    exit 1
  fi
fi

nohup .venv/bin/python3 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "\$APP_PORT" >> app.log 2>&1 < /dev/null &
new_pid=\$!
sleep 2
if ! kill -0 "\$new_pid" 2>/dev/null; then
  echo "new process exited"
  tail -80 app.log
  exit 1
fi

curl -fsS -m 8 "http://127.0.0.1:\$APP_PORT/api/health" >/tmp/text_image_health.json
curl -fsS -m 8 "http://127.0.0.1:\$APP_PORT/api/workflow/board" >/tmp/text_image_workflow_board.json
echo "Backend deployed with pid=\$new_pid"
REMOTE
