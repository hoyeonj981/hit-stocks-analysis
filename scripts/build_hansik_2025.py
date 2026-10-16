"""실행: ./scripts/uv run --locked python scripts/build_hansik_2025.py"""

import json

from hit_stocks_analysis import find_project_root
from hit_stocks_analysis.hansik_dataset import build_dataset

if __name__ == "__main__":
    print(json.dumps(build_dataset(find_project_root()), ensure_ascii=False, indent=2))
