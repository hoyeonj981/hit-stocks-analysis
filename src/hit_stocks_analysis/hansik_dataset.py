"""지정 연도 전체 상품을 선별하고 원본 출고 행·시간별 순위를 재구축합니다."""

import hashlib
import json
from pathlib import Path

import duckdb
import pandas as pd

from .hansik import classify_products, load_reference


def build_dataset(root: Path, year: int = 2025) -> dict:
    year = int(year)
    files = sorted(root.glob(f"outbound_{year}-*.csv"))
    if not files:
        raise FileNotFoundError(f"프로젝트 루트에 outbound_{year}-*.csv가 필요합니다.")
    data = root / f"data/hansik_{year}"
    report = root / f"reports/hansik_{year}"
    data.mkdir(parents=True, exist_ok=True)
    report.mkdir(parents=True, exist_ok=True)
    rules, sources = load_reference(root)
    with duckdb.connect() as con:
        con.read_csv([str(p) for p in files], all_varchar=True).create_view("raw")
        con.execute(f"""
            CREATE TEMP TABLE prepared AS
            SELECT *, TRY_CAST(outboundRequestDateTime AS TIMESTAMP) AS requested_at,
                   NULLIF(TRIM("orderId(주문번호)"), '') AS order_id,
                   NULLIF(TRIM(skuCode), '') AS sku_code,
                   TRY_CAST(pickingQuantity AS DOUBLE) AS picked_quantity
            FROM raw;
            CREATE TEMP VIEW year_rows AS SELECT * FROM prepared
            WHERE requested_at >= TIMESTAMP '{year}-01-01'
              AND requested_at < TIMESTAMP '{year + 1}-01-01';
            CREATE TEMP TABLE eligible AS
            SELECT *, EXTRACT(hour FROM requested_at)::INTEGER AS hour FROM year_rows
            WHERE status = 'SHIPPED' AND picked_quantity > 0
              AND order_id IS NOT NULL AND sku_code IS NOT NULL;
        """)
        products = con.execute("""
            WITH catalog AS (
                SELECT sku_code, ARG_MAX(skuName, requested_at) AS sku_name,
                       COUNT(DISTINCT skuName) AS name_variant_count
                FROM year_rows WHERE sku_code IS NOT NULL GROUP BY sku_code
            ), totals AS (
                SELECT sku_code, COUNT(DISTINCT order_id) AS annual_order_count,
                       SUM(picked_quantity) AS annual_picked_quantity,
                       COUNT(*) AS outbound_rows FROM eligible GROUP BY sku_code
            )
            SELECT c.*, COALESCE(t.annual_order_count, 0) AS annual_order_count,
                   COALESCE(t.annual_picked_quantity, 0) AS annual_picked_quantity,
                   COALESCE(t.outbound_rows, 0) AS outbound_rows
            FROM catalog c LEFT JOIN totals t USING(sku_code)
            ORDER BY annual_order_count DESC, annual_picked_quantity DESC, sku_code
        """).df()
        audit = classify_products(products, rules, sources)
        variants = (audit.name_variant_count > 1) & (audit.classification == "included")
        audit.loc[variants, "classification"] = "review"
        audit.loc[variants, "classification_reason"] = "동일 SKU의 여러 상품명 확인 필요"
        selected = audit[audit.classification == "included"].copy()
        assert selected.sku_code.is_unique and selected.source_urls.ne("").all()
        con.register("selected", selected)
        con.execute("""
            CREATE TEMP TABLE filtered AS
            SELECT e.*, s.ingredient_names, s.ingredient_categories, s.rule_ids,
                   s.source_ids, s.source_urls
            FROM eligible e JOIN selected s USING(sku_code)
        """)
        # 원본 12개 열을 보존하며 SKU에 한 번만 연결하여 출고 행이 증식하지 않습니다.
        con.table("filtered").order("requested_at, order_id, sku_code, splitOrderId").write_parquet(
            str(data / "outbound_ingredients.parquet"), compression="zstd"
        )
        hourly = con.execute("""
            SELECT h.hour, COUNT(DISTINCT f.order_id) AS ingredient_orders,
                   COUNT(DISTINCT f.sku_code) AS distinct_skus,
                   COALESCE(SUM(f.picked_quantity), 0) AS picked_quantity
            FROM range(24) h(hour) LEFT JOIN filtered f ON h.hour = f.hour
            GROUP BY h.hour ORDER BY h.hour
        """).df()
        ranked = (
            con.execute("""
            WITH counts AS (
                SELECT hour, sku_code, COUNT(DISTINCT order_id) AS order_count,
                       SUM(picked_quantity) AS picked_quantity
                FROM filtered GROUP BY hour, sku_code
            )
            SELECT c.*, ROW_NUMBER() OVER (
                PARTITION BY hour ORDER BY order_count DESC, picked_quantity DESC, sku_code
            ) AS rank, s.sku_name, s.ingredient_names, s.ingredient_categories,
                s.source_ids, s.source_urls
            FROM counts c JOIN selected s USING(sku_code) ORDER BY hour, rank
        """)
            .df()
            .merge(hourly[["hour", "ingredient_orders"]], on="hour", how="left")
        )
        ranked["ingredient_order_share_pct"] = (
            ranked.order_count / ranked.ingredient_orders * 100
        ).round(2)
        stats = (
            con.execute("""
            SELECT COUNT(*) AS selected_outbound_rows,
                   COUNT(DISTINCT order_id) AS selected_unique_orders,
                   COALESCE(SUM(picked_quantity), 0) AS selected_picked_quantity
            FROM filtered
        """)
            .df()
            .iloc[0]
            .to_dict()
        )
        stats["input_rows"] = con.table("prepared").count("*").fetchone()[0]
        stats["eligible_rows"] = con.table("eligible").count("*").fetchone()[0]
        stats["missing_dates"] = [
            str(r[0])
            for r in con.execute(f"""
            SELECT CAST(day AS DATE) FROM generate_series(
                DATE '{year}-01-01', DATE '{year}-12-31', INTERVAL 1 DAY
            ) t(day) WHERE CAST(day AS DATE) NOT IN (
                SELECT DISTINCT CAST(requested_at AS DATE) FROM year_rows
            ) ORDER BY day
        """).fetchall()
        ]
        assert stats["selected_outbound_rows"] == int(selected.outbound_rows.sum())
        assert stats["selected_picked_quantity"] == selected.annual_picked_quantity.sum()
        assert ranked.order_count.le(ranked.ingredient_orders).all()
        assert hourly.picked_quantity.sum() == stats["selected_picked_quantity"]
    for field in ("selected_outbound_rows", "selected_unique_orders"):
        stats[field] = int(stats[field])
    stats.update(
        {
            "catalog_skus": len(audit),
            "selected_skus": len(selected),
            "classification_counts": audit.classification.value_counts().to_dict(),
            "ingredient_rules": len(rules),
            "sources": len(sources),
            "source_files": [p.name for p in files],
            "time_column": "outboundRequestDateTime; timezone unspecified; no conversion",
            "definition": "공개 자료에 한식 사용 근거가 있는 재료의 상품명 기반 선별 후보",
            "reference_sha256": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (root / "references/hansik").glob("*")
                if p.suffix in {".csv", ".json"}
            },
        }
    )
    # 식재료 자료와 SKU 분류 규칙을 결과 옆에도 함께 저장합니다.
    frames = {
        "products": selected,
        "classification_audit": audit,
        "review_products": audit[audit.classification == "review"],
        "unmatched_products": audit[audit.classification == "not_matched"],
        "ingredient_rules": rules,
        "sources": sources,
    }
    for name, frame in frames.items():
        frame.to_csv(data / f"{name}.csv", index=False, encoding="utf-8-sig")
    selected.to_parquet(data / "products.parquet", index=False)
    for name, frame in {
        "hourly_all_products": ranked,
        "hourly_top10": ranked[ranked["rank"] <= 10],
        "hourly_summary": hourly,
    }.items():
        frame.to_csv(report / f"{name}.csv", index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(report / f"hansik_ingredients_{year}.xlsx") as writer:
        for name, frame in {
            "선별상품": selected,
            "시간별_TOP10": ranked[ranked["rank"] <= 10],
            "시간별_재료주문": hourly,
            "전체상품_분류": audit,
            "재료별_근거": rules,
            "출처": sources,
        }.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    (report / "summary.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n")
    return stats
