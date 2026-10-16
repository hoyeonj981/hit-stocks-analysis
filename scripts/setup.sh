#!/bin/sh
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_ROOT"
if [ ! -x .tools/uv/bin/uv ]; then
    python3 -m venv .tools/uv
    PIP_CACHE_DIR="$PROJECT_ROOT/.cache/pip" .tools/uv/bin/python -m pip install 'uv>=0.9,<1'
fi
if [ -f uv.lock ]; then
    ./scripts/uv sync --locked
else
    ./scripts/uv sync
fi
./scripts/uv run python -m ipykernel install --sys-prefix \
    --name hit-stocks-analysis --display-name 'Python (hit-stocks-analysis)'
echo '설치 완료. ./scripts/lab.sh 로 JupyterLab을 실행하세요.'
