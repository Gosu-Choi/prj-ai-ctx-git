#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
repo_root="$(cd "$script_dir/../.." >/dev/null 2>&1 && pwd)"

if [[ -f "$repo_root/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$repo_root/.env"
  set +a
fi

host="${CTXGIT_HOST:-127.0.0.1}"
port="${CTXGIT_PORT:-8766}"
root="${CTXGIT_ROOT:-}"
foreground=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --foreground)
      foreground=1
      shift
      ;;
    --host)
      host="${2:?missing host}"
      shift 2
      ;;
    --port)
      port="${2:?missing port}"
      shift 2
      ;;
    *)
      root="$1"
      shift
      ;;
  esac
done

if [[ -z "$root" ]]; then
  root="$PWD"
fi
if [[ ! -d "$root" ]]; then
  echo "ctxgit: project root does not exist: $root" >&2
  exit 1
fi
root="$(cd "$root" >/dev/null 2>&1 && pwd)"

python_cmd="${PYTHON:-python3}"
if ! command -v "$python_cmd" >/dev/null 2>&1; then
  echo "ctxgit: $python_cmd was not found." >&2
  exit 1
fi
if ! "$python_cmd" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
  echo "ctxgit: Python 3.10+ is required." >&2
  exit 1
fi

existing_pids=""
if command -v lsof >/dev/null 2>&1; then
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ "$command_line" == *"ctxgit.py"* && "$command_line" == *" serve "* ]]; then
      existing_pids+="$pid "
    fi
  done < <(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
fi

if [[ -n "$existing_pids" ]]; then
  echo "ctxgit server is already running on http://$host:$port/"
  echo "PID(s): $existing_pids"
  exit 0
fi

ctxgit_py="$repo_root/tools/ctxgit/ctxgit.py"
args=("$ctxgit_py" "--root" "$root" "serve" "--host" "$host" "--port" "$port")

if [[ "$foreground" == "1" ]]; then
  exec "$python_cmd" "${args[@]}"
fi

log_dir="$repo_root/.ctxgit/logs"
mkdir -p "$log_dir"
stdout_path="$log_dir/server-$port.out.log"
stderr_path="$log_dir/server-$port.err.log"
pid_path="$repo_root/.ctxgit/server-$port.pid"

nohup "$python_cmd" "${args[@]}" >"$stdout_path" 2>"$stderr_path" &
pid="$!"
printf '%s\n' "$pid" >"$pid_path"

url="http://$host:$port/"
started=0
for _ in $(seq 1 30); do
  sleep 0.3
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_path"
    echo "ctxgit server exited during startup." >&2
    tail -40 "$stderr_path" 2>/dev/null || true
    exit 1
  fi
  if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 1 "${url}api/auth/status" >/dev/null 2>&1; then
    started=1
    break
  fi
done

if [[ "$started" != "1" ]]; then
  echo "ctxgit server process started but did not respond at $url within 10 seconds." >&2
  exit 1
fi

echo "ctxgit server started: http://$host:$port/"
echo "PID: $pid"
echo "Root: $root"
echo "Logs: $stdout_path ; $stderr_path"
