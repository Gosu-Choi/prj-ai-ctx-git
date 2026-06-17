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

port="${CTXGIT_PORT:-8766}"
if [[ $# -gt 0 ]]; then
  port="$1"
fi

pid_path="$repo_root/.ctxgit/server-$port.pid"
targets=()

if [[ -f "$pid_path" ]]; then
  pid="$(cat "$pid_path" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ "$command_line" == *"ctxgit.py"* && "$command_line" == *" serve "* ]]; then
      targets+=("$pid")
    fi
  fi
fi

if command -v lsof >/dev/null 2>&1; then
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ "$command_line" == *"ctxgit.py"* && "$command_line" == *" serve "* ]]; then
      targets+=("$pid")
    fi
  done < <(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
fi

if [[ "${#targets[@]}" -eq 0 ]]; then
  echo "No ctxgit server found on port $port."
  rm -f "$pid_path"
  exit 0
fi

unique_targets="$(printf '%s\n' "${targets[@]}" | awk '!seen[$0]++')"
while IFS= read -r pid; do
  [[ -z "$pid" ]] && continue
  echo "Stopping ctxgit server PID $pid"
  kill "$pid" 2>/dev/null || true
done <<< "$unique_targets"

rm -f "$pid_path"
echo "ctxgit server stopped on port $port."
