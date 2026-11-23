#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -c "import fastapi, uvicorn, multipart" 2>/dev/null || .venv/bin/pip install -r requirements.txt
exec .venv/bin/python run.py "$@"
