#!/bin/sh
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec "$PROJECT_ROOT/scripts/uv" run --locked jupyter lab --no-browser --ip=127.0.0.1 "$@"
