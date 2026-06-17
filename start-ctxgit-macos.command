#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd)"

if [[ -f "$repo_dir/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$repo_dir/.env"
  set +a
fi

bash "$repo_dir/scripts/macos/start-ctxgit.sh"
