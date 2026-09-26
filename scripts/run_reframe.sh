#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repo_dir"
exec "$repo_dir/.venv/bin/python" "$repo_dir/src/reframe.py" "$@"
