#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${ACTION_REFRAME_PYTHON:-$repo_dir/.venv/bin/python}" "$repo_dir/src/reframe.py" "$@"
