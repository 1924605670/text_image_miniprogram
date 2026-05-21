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

exec 9>"\$APP_DIR/.deploy.lock"
if ! flock -w 300 9; then
  echo "Timed out waiting for another deployment to finish for \$APP_DIR"
  exit 1
fi

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m compileall app
.venv/bin/python -c "import app.main; print('import ok')"

listener_pids() {
  ss -H -ltnp "sport = :\$APP_PORT" 2>/dev/null \
    | grep -o 'pid=[0-9][0-9]*' \
    | cut -d= -f2 \
    | sort -u || true
}

old_pids=\$(listener_pids)
if [ -n "\${old_pids:-}" ]; then
  for old_pid in \$old_pids; do
    old_cwd=\$(readlink "/proc/\$old_pid/cwd" 2>/dev/null || true)
    if [ "\$old_cwd" != "\$APP_DIR" ]; then
      echo "Refusing to stop pid \$old_pid with cwd=\$old_cwd"
      exit 1
    fi
  done

  kill \$old_pids
  for _ in \$(seq 1 60); do
    live_pids=""
    for old_pid in \$old_pids; do
      if kill -0 "\$old_pid" 2>/dev/null; then
        live_pids="\$live_pids \$old_pid"
      fi
    done
    port_pids=\$(listener_pids)
    if [ -z "\${live_pids:-}" ] && [ -z "\${port_pids:-}" ]; then
      break
    fi
    sleep 0.5
  done

  port_pids=\$(listener_pids)
  if [ -n "\${port_pids:-}" ]; then
    echo "Port \$APP_PORT is still in use by pid(s): \$port_pids"
    exit 1
  fi
fi

nohup .venv/bin/python3 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "\$APP_PORT" >> app.log 2>&1 < /dev/null &
new_pid=\$!

health_ok=0
for _ in \$(seq 1 60); do
  if ! kill -0 "\$new_pid" 2>/dev/null; then
    echo "new process exited"
    tail -80 app.log
    exit 1
  fi
  if curl -fsS -m 4 "http://127.0.0.1:\$APP_PORT/api/health" >/tmp/text_image_health.json 2>/dev/null; then
    health_ok=1
    break
  fi
  sleep 1
done
if [ "\$health_ok" != "1" ]; then
  echo "new process did not become healthy in time"
  tail -80 app.log
  exit 1
fi

curl -fsS -m 8 "http://127.0.0.1:\$APP_PORT/api/health" >/tmp/text_image_health.json
curl -fsS -m 8 "http://127.0.0.1:\$APP_PORT/api/options" >/tmp/text_image_options.json
echo "Backend deployed with pid=\$new_pid"
REMOTE
