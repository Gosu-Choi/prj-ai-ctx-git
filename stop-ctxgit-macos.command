#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd)"
bash "$repo_dir/scripts/macos/stop-ctxgit.sh"
