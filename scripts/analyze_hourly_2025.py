"""2025년 출고 요청 시간별 상품 주문 빈도 집계.

실행: ./scripts/uv run python scripts/analyze_hourly_2025.py
"""

import json
from pathlib import Path

import duckdb
import matplotlib
import pandas as pd

from hit_stocks_analysis import find_project_root

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402


def aggregate(connection: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, pd.DataFrame]:
    """raw 뷰를 읽어 시간대·SKU별 순위와 시간대 전체 주문 수를 반환합니다."""
    connection.execute("""
        CREATE OR REPLACE TEMP TABLE prepared AS
        SELECT TRY_CAST(outboundRequestDateTime AS TIMESTAMP) AS requested_at,
               NULLIF(TRIM("orderId(주문번호)"), '') AS order_id,
               NULLIF(TRIM(skuCode), '') AS sku_code,
               skuName AS sku_name, status,
               TRY_CAST(pickingQuantity AS DOUBLE) AS picked_quantity
        FROM raw
    """)
    connection.execute("""
        CREATE OR REPLACE TEMP TABLE eligible AS
        SELECT *, EXTRACT(hour FROM requested_at)::INTEGER AS hour
        FROM prepared
        WHERE requested_at >= TIMESTAMP '2025-01-01'
          AND requested_at < TIMESTAMP '2026-01-01'
          AND status = 'SHIPPED' AND picked_quantity > 0
          AND order_id IS NOT NULL AND sku_code IS NOT NULL
    """)
    ranked = connection.execute("""
        WITH grouped AS (
            SELECT hour, sku_code, ARG_MAX(sku_name, requested_at) AS sku_name,
                   COUNT(DISTINCT order_id) AS order_count,
                   SUM(picked_quantity) AS picked_quantity
            FROM eligible GROUP BY hour, sku_code
        )
        SELECT hour,
               ROW_NUMBER() OVER (
                   PARTITION BY hour ORDER BY order_count DESC, picked_quantity DESC, sku_code
               ) AS rank,
               sku_code, sku_name, order_count, picked_quantity
        FROM grouped ORDER BY hour, rank
    """).df()
    hourly = connection.execute("""
        SELECT h.hour, COUNT(DISTINCT e.order_id) AS total_orders,
               COUNT(DISTINCT e.sku_code) AS distinct_skus,
               COALESCE(SUM(e.picked_quantity), 0) AS picked_quantity
        FROM range(24) h(hour) LEFT JOIN eligible e ON h.hour = e.hour
        GROUP BY h.hour ORDER BY h.hour
    """).df()
    ranked = ranked.merge(hourly[["hour", "total_orders"]], on="hour", how="left")
    ranked["order_share_pct"] = (100 * ranked["order_count"] / ranked["total_orders"]).round(2)
    return ranked, hourly


def save_chart(ranked: pd.DataFrame, output: Path) -> None:
    fonts = {font.name for font in font_manager.fontManager.ttflist}
    for font in ("AppleGothic", "Malgun Gothic", "NanumGothic"):
        if font in fonts:
            plt.rcParams["font.family"] = font
            break
    plt.rcParams["axes.unicode_minus"] = False
    # 각 시간대 TOP 3에 한 번이라도 등장한 상품의 시간대별 주문 수.
    codes = ranked.loc[ranked["rank"] <= 3, "sku_code"].drop_duplicates()
    names = ranked.drop_duplicates("sku_code").set_index("sku_code")["sku_name"]
    values = ranked.pivot(index="sku_code", columns="hour", values="order_count")
    values = values.reindex(index=codes, columns=range(24)).fillna(0)
    fig, ax = plt.subplots(figsize=(16, max(5, len(codes) * 0.5)))
    plot = ax.imshow(values, aspect="auto", cmap="YlOrRd")
    ax.set_xticks(range(24), [f"{hour:02d}" for hour in range(24)])
    ax.set_yticks(range(len(codes)), [f"{names[sku]} [{sku}]" for sku in codes])
    ax.set(
        xlabel="출고 요청 시각 (원본 시각, 시간대 변환 없음)",
        title="2025년 시간대별 상품 주문 빈도 · 8월 31일 자료 없음",
    )
    fig.colorbar(plot, ax=ax, label="상품별 고유 주문 건수")
    fig.tight_layout()
    fig.savefig(output / "hourly_top_products.png", dpi=160)
    plt.close(fig)


def main() -> None:
    root = find_project_root()
    files = sorted(root.glob("outbound_2025-*.csv"))
    if not files:
        raise FileNotFoundError("2025년 outbound CSV가 없습니다.")
    output = root / "reports" / "hourly_2025"
    output.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.read_csv([str(path) for path in files], all_varchar=True).create_view("raw")
        ranked, hourly = aggregate(connection)
        quality = (
            connection.execute("""
            SELECT COUNT(*) AS input_rows,
                   COUNT(*) FILTER (WHERE requested_at IS NULL) AS invalid_timestamp_rows,
                   COUNT(*) FILTER (WHERE picked_quantity IS NULL) AS invalid_quantity_rows,
                   COUNT(*) FILTER (WHERE picked_quantity <= 0) AS nonpositive_quantity_rows,
                   COUNT(*) FILTER (WHERE order_id IS NULL OR sku_code IS NULL) AS missing_id_rows,
                   COUNT(*) FILTER (WHERE status IS DISTINCT FROM 'SHIPPED') AS not_shipped_rows,
                   COUNT(*) FILTER (WHERE requested_at < TIMESTAMP '2025-01-01'
                       OR requested_at >= TIMESTAMP '2026-01-01') AS outside_2025_rows
            FROM prepared
        """)
            .df()
            .iloc[0]
            .astype(int)
            .to_dict()
        )
        quality.update(
            connection.execute("""
            SELECT COUNT(*) AS eligible_rows, COUNT(DISTINCT order_id) AS unique_orders,
                   COUNT(DISTINCT sku_code) AS unique_skus,
                   SUM(picked_quantity) AS total_picked_quantity
            FROM eligible
        """)
            .df()
            .iloc[0]
            .to_dict()
        )
        quality["missing_dates"] = [
            str(row[0])
            for row in connection.execute("""
            SELECT CAST(day AS DATE) FROM generate_series(
                DATE '2025-01-01', DATE '2025-12-31', INTERVAL 1 DAY
            ) t(day)
            WHERE CAST(day AS DATE) NOT IN (
                SELECT DISTINCT CAST(requested_at AS DATE) FROM prepared
                WHERE requested_at IS NOT NULL
            ) ORDER BY day
        """).fetchall()
        ]
    for key in ("eligible_rows", "unique_orders", "unique_skus"):
        quality[key] = int(quality[key])
    quality["source_files"] = [path.name for path in files]
    quality["time_column"] = "outboundRequestDateTime (timezone unspecified; no conversion)"
    top10 = ranked[ranked["rank"] <= 10]
    for name, frame in (
        ("hourly_all_products", ranked),
        ("hourly_top10", top10),
        ("hourly_summary", hourly),
    ):
        frame.to_csv(output / f"{name}.csv", index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(output / "hourly_products_2025.xlsx") as writer:
        top10.to_excel(writer, sheet_name="시간별_TOP10", index=False)
        ranked.to_excel(writer, sheet_name="전체_상품_순위", index=False)
        hourly.to_excel(writer, sheet_name="시간별_전체주문", index=False)
        pd.DataFrame({"항목": list(quality), "값": [str(v) for v in quality.values()]}).to_excel(
            writer, sheet_name="데이터_점검", index=False
        )
    (output / "data_quality.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    save_chart(ranked, output)
    lines = [
        "# 2025년 출고 요청 시간별 자주 출고된 상품",
        "",
        "시간: outboundRequestDateTime의 시(hour). 실제 출고 완료 시각이 아닙니다.",
        "원본에 시간대 정보가 없어 시간대 변환 없이 사용했습니다.",
        "대상: 2025년, SHIPPED, pickingQuantity > 0, 주문번호·SKU가 있는 행.",
        "빈도: 시간대·SKU별 고유 주문번호 수. 분할 행은 주문 수에서 중복 계산하지 않습니다.",
        "수량: 대상 행의 pickingQuantity 합계. 동률은 수량 내림차순, SKU 오름차순입니다.",
        "비중: 해당 상품 주문 수 / 해당 시간대 전체 고유 주문 수. "
        "상품 간 합은 100%를 넘을 수 있습니다.",
        "주문 하나가 여러 시간에 나타나면 각 시간에 집계됩니다. "
        "시간별 합과 연간 고유 주문 수는 다를 수 있습니다.",
        f"자료 없는 날짜: {', '.join(quality['missing_dates']) or '없음'}. "
        "무출고로 단정하지 않습니다.",
        "",
        "| 시간 | 전체 주문 | 1위 (주문 수) | 2위 (주문 수) | 3위 (주문 수) |",
        "|---|---:|---|---|---|",
    ]
    for row in hourly.itertuples():
        top = ranked[(ranked["hour"] == row.hour) & (ranked["rank"] <= 3)]
        products = [f"{r.sku_name} ({r.order_count:,})" for r in top.itertuples()]
        products += ["—"] * (3 - len(products))
        lines.append(
            f"| {row.hour:02d}:00–{row.hour:02d}:59 | {row.total_orders:,} | "
            + " | ".join(products)
            + " |"
        )
    report = "\n".join(lines) + "\n"
    (output / "summary.md").write_text(report, encoding="utf-8")
    print(json.dumps(quality, ensure_ascii=False, indent=2))
    print(report)
    print(f"저장 위치: {output}")


if __name__ == "__main__":
    main()
