#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd)"

if [[ -f "$repo_dir/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$repo_dir/.env"
  set +a
fi

project_root="${CTXGIT_ROOT:-}"
if [[ -z "$project_root" && -d "$repo_dir/../../Lit review" ]]; then
  project_root="$(cd "$repo_dir/../../Lit review" >/dev/null 2>&1 && pwd)"
fi
if [[ -z "$project_root" ]]; then
  project_root="$repo_dir"
fi

bash "$repo_dir/scripts/macos/start-ctxgit.sh" "$project_root"
