"""기존 2025년 재료 데이터셋에서 분기별 TOP 15 히트맵을 생성합니다."""

import json

from hit_stocks_analysis import find_project_root
from hit_stocks_analysis.hansik_quarterly import build_quarterly_heatmaps

if __name__ == "__main__":
    result = build_quarterly_heatmaps(find_project_root(), year=2025, rebuild_dataset=False)
    print(json.dumps(result, ensure_ascii=False, indent=2))
