#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$repo_dir/src${PYTHONPATH:+:$PYTHONPATH}"
exec "${ACTION_REFRAME_PYTHON:-$repo_dir/.venv/bin/python}" -m unittest discover -s "$repo_dir/tests" -v "$@"
