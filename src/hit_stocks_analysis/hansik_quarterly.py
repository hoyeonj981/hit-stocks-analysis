"""분기별 한식 재료 TOP 15의 시간대별 고유 주문 빈도."""

import json
from pathlib import Path

import duckdb
import matplotlib
import pandas as pd

from .hansik_dataset import build_dataset

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import seaborn as sns  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from openpyxl.drawing.image import Image as ExcelImage  # noqa: E402
from openpyxl.formatting.rule import ColorScaleRule  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402


def aggregate_quarterly(con: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, pd.DataFrame]:
    """선별 완료된 outbound 뷰를 달력 분기 경계로 나눕니다."""
    products = con.execute("""
        WITH counts AS (
            SELECT EXTRACT(quarter FROM requested_at)::INTEGER AS quarter, sku_code,
                   COUNT(DISTINCT order_id) AS quarter_order_count,
                   SUM(picked_quantity) AS quarter_picked_quantity
            FROM outbound GROUP BY quarter, sku_code
        )
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY quarter
            ORDER BY quarter_order_count DESC, quarter_picked_quantity DESC, sku_code
        ) AS quarter_rank FROM counts ORDER BY quarter, quarter_rank
    """).df()
    hourly = con.execute("""
        SELECT EXTRACT(quarter FROM requested_at)::INTEGER AS quarter, hour, sku_code,
               COUNT(DISTINCT order_id) AS order_count,
               SUM(picked_quantity) AS picked_quantity
        FROM outbound GROUP BY quarter, hour, sku_code ORDER BY quarter, hour, sku_code
    """).df()
    return products, hourly


def build_quarterly_heatmaps(
    root: Path, year: int = 2026, *, rebuild_dataset: bool = True
) -> dict:
    data, report = root / f"data/hansik_{year}", root / f"reports/hansik_{year}"
    # 기존 재료 데이터셋을 재사용하면 연간 Excel에 추가된 히트맵도 보존됩니다.
    summary = (
        build_dataset(root, year=year)
        if rebuild_dataset
        else json.loads((report / "summary.json").read_text())
    )
    with duckdb.connect() as con:
        con.read_parquet(str(data / "outbound_ingredients.parquet")).create_view("outbound")
        ranked, hourly = aggregate_quarterly(con)
        con.read_csv(
            [str(p) for p in sorted(root.glob(f"outbound_{year}-*.csv"))], all_varchar=True
        ).create_view("raw")
        dates = (
            con.execute(
                """
            SELECT DISTINCT CAST(TRY_CAST(outboundRequestDateTime AS TIMESTAMP) AS DATE) AS day
            FROM raw WHERE EXTRACT(year FROM TRY_CAST(outboundRequestDateTime AS TIMESTAMP)) = ?
            ORDER BY day
        """,
                [year],
            )
            .df()
            .day
        )
    observed = set(pd.to_datetime(dates).dt.strftime("%Y-%m-%d"))
    coverage = []
    for q in range(1, 5):
        calendar = pd.date_range(f"{year}-{3 * q - 2:02d}-01", periods=1)[0]
        calendar = pd.date_range(calendar, calendar + pd.offsets.QuarterEnd())
        expected = set(calendar.strftime("%Y-%m-%d"))
        available = sorted(expected & observed)
        coverage.append(
            {
                "quarter": q,
                "calendar_start": str(calendar[0].date()),
                "calendar_end": str(calendar[-1].date()),
                "observed_start": available[0] if available else "",
                "observed_end": available[-1] if available else "",
                "observed_days": len(available),
                "calendar_days": len(calendar),
                "coverage_status": "자료 없음"
                if not available
                else ("전체 날짜 관측" if len(available) == len(calendar) else "일부 기간 자료"),
                "unobserved_dates": ";".join(sorted(expected - observed)),
            }
        )
    coverage = pd.DataFrame(coverage)
    products = pd.read_csv(data / "products.csv", dtype={"sku_code": str})
    ranked = ranked.merge(
        products[["sku_code", "sku_name", "ingredient_names", "source_urls"]],
        on="sku_code",
        validate="many_to_one",
    )
    top = ranked[ranked.quarter_rank <= 15].copy()
    assert hourly.picked_quantity.sum() == summary["selected_picked_quantity"]
    assert ranked.quarter_picked_quantity.sum() == summary["selected_picked_quantity"]
    for name, frame in {
        "quarterly_products": ranked,
        "quarterly_top15": top,
        "quarterly_hourly_products": hourly,
        "quarterly_coverage": coverage,
    }.items():
        frame.to_csv(report / f"{name}.csv", index=False, encoding="utf-8-sig")
    matrices = {}
    for q, group in top.groupby("quarter", sort=True):
        matrix = (
            hourly[hourly.quarter == q]
            .pivot(index="sku_code", columns="hour", values="order_count")
            .reindex(index=group.sku_code, columns=range(24))
            .fillna(0)
            .astype(int)
        )
        matrices[q] = matrix
    vmax = max((int(m.to_numpy().max()) for m in matrices.values()), default=1)
    fonts = {font.name for font in font_manager.fontManager.ttflist}
    for font in ("AppleGothic", "Malgun Gothic", "NanumGothic"):
        if font in fonts:
            plt.rcParams["font.family"] = font
            break
    plt.rcParams["axes.unicode_minus"] = False
    images = []
    with pd.ExcelWriter(report / f"hansik_ingredients_{year}_quarterly.xlsx") as writer:
        coverage.to_excel(writer, sheet_name="분기별_자료기간", index=False)
        top.to_excel(writer, sheet_name="분기별_TOP15", index=False)
        hourly.to_excel(writer, sheet_name="분기별_시간대빈도", index=False)
        for q, matrix in matrices.items():
            group = top[top.quarter == q].reset_index(drop=True)
            info = coverage.set_index("quarter").loc[q]
            period = f"{info.observed_start} ~ {info.observed_end} · {info.observed_days}일 관측"
            missing_note = ""
            if info.unobserved_dates:
                missing_dates = info.unobserved_dates.split(";")
                missing_note = (
                    f"미관측 날짜: {', '.join(missing_dates)}. "
                    if len(missing_dates) <= 3
                    else f"미관측 {len(missing_dates)}일: 자료기간 표 참조. "
                )
            fig, ax = plt.subplots(figsize=(22, 10))
            labels = [
                f"{r.quarter_rank:02d}  {r.sku_name}  ({r.quarter_order_count:,}건)"
                for r in group.itertuples()
            ]
            sns.heatmap(
                matrix,
                ax=ax,
                cmap="YlOrRd",
                vmin=0,
                vmax=vmax,
                annot=True,
                fmt=",d",
                annot_kws={"fontsize": 8},
                linewidths=0.5,
                linecolor="white",
                xticklabels=[f"{h:02d}" for h in range(24)],
                yticklabels=labels,
                cbar_kws={"label": "고유 주문 건수 · 분기 공통 눈금", "shrink": 0.8},
            )
            ax.set_title(f"{year}년 {q}분기 한식 조리 재료 TOP 15\n{period}", fontsize=19, pad=18)
            ax.set_xlabel("출고 요청 시각 (0–23시 · 원본 시각 기준)", labelpad=12)
            ax.set_ylabel("분기 고유 주문 수 순위 · 상품명 · 분기 주문 건수", labelpad=15)
            ax.tick_params(axis="y", labelrotation=0, labelsize=10, length=0)
            ax.tick_params(axis="x", labelrotation=0, labelsize=10, length=0)
            fig.text(
                0.02,
                0.025,
                "분기별 고유 주문 수 상위 15개 SKU를 각각 선정. "
                "칸의 숫자는 상품·시간대별 고유 주문 건수이며 일평균이 아닙니다.\n"
                f"자료 상태: {info.coverage_status}. 미관측 날짜를 무출고로 간주하지 않습니다. "
                "분기별 관측 일수·상품 구성이 다를 수 있습니다. 실제 출고 완료 시각 아님."
                + (f"\n{missing_note}" if missing_note else ""),
                fontsize=10,
                color="#555555",
            )
            fig.tight_layout(rect=(0, 0.08, 1, 1))
            path = report / f"hansik_{year}_Q{q}_top15_hourly_heatmap.png"
            fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
            plt.close(fig)
            images.append(path.name)
            table = group[["quarter_rank", "sku_code", "sku_name", "quarter_order_count"]].copy()
            for h in range(24):
                table[f"{h:02d}시"] = matrix[h].to_numpy()
            table.to_csv(
                report / f"hansik_{year}_Q{q}_top15_hourly_heatmap.csv",
                index=False,
                encoding="utf-8-sig",
            )
            sheet_name = f"Q{q}_TOP15_히트맵"
            table.to_excel(writer, sheet_name=sheet_name, index=False, startrow=3)
            sheet = writer.sheets[sheet_name]
            sheet["A1"] = f"{year}년 {q}분기 TOP 15 / {period} / {info.coverage_status}"
            sheet["A2"] = (
                "출고 요청 시각 기준 · 고유 주문 건수 · 분기 공통 색상 눈금. " + missing_note
            )
            sheet.freeze_panes = "E5"
            for column, width in {"A": 14, "B": 16, "C": 46, "D": 24}.items():
                sheet.column_dimensions[column].width = width
            for column in range(5, 29):
                sheet.column_dimensions[get_column_letter(column)].width = 9
            sheet.conditional_formatting.add(
                f"E5:AB{4 + len(table)}",
                ColorScaleRule(
                    start_type="num",
                    start_value=0,
                    start_color="FFFFCC",
                    mid_type="num",
                    mid_value=vmax / 2,
                    mid_color="FD8D3C",
                    end_type="num",
                    end_value=vmax,
                    end_color="800026",
                ),
            )
            picture = ExcelImage(path)
            picture.width, picture.height = 1650, picture.height * 1650 / picture.width
            sheet.add_image(picture, "A23")
    result = {
        "year": year,
        "selected_skus": summary["selected_skus"],
        "selected_outbound_rows": summary["selected_outbound_rows"],
        "coverage": coverage.to_dict(orient="records"),
        "heatmaps": images,
        "common_color_max": vmax,
        "top_n": 15,
    }
    (report / "quarterly_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    return result
