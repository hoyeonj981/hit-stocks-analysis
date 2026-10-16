"""실행: ./scripts/uv run python scripts/analyze_mfc_order_distance.py"""

import matplotlib

from hit_stocks_analysis import find_project_root

matplotlib.use("Agg")

from hit_stocks_analysis.mfc_order_distance import build_report  # noqa: E402

if __name__ == "__main__":
    result = build_report(find_project_root())
    print(result["folder"])
    print({key: result["summary"][key] for key in (
        "orders", "complete_orders", "mean_cost", "max_cost", "longest_order_id",
        "nearest_mean_order_id")})
