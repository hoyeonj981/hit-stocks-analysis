"""2026년 분기별 한식 재료 TOP 15 데이터·히트맵·Excel 재생성."""

import json

from hit_stocks_analysis import find_project_root
from hit_stocks_analysis.hansik_quarterly import build_quarterly_heatmaps

if __name__ == "__main__":
    print(json.dumps(build_quarterly_heatmaps(find_project_root()), ensure_ascii=False, indent=2))
