"""9월 주문별 할당 렉 방문과 단순 거리 비용 분석."""

import json

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.colors import ListedColormap, Normalize
from matplotlib.patches import Rectangle

TITLES = {"A": "A · 냉동", "B": "B · 냉장", "C_D": "C·D · 상온"}


def rack_cost_features(layout, model):
    """같은 깊이 블록의 측방 진입을 묶는 근사. 실제 이동 경로는 아니다."""
    rows = []
    for code, cell in layout.racks.loc[layout.racks["observed"]].iterrows():
        rule = model["areas"][cell.area]
        px, py = cell.cx, cell.cy
        aisle = f"{int(cell.aisle):02}"
        faces = layout.rules["face_rows"][cell.zone].get(aisle)
        if faces is not None:
            py = sum(faces) / 2  # 같은 복도의 양쪽 렉은 같은 통로 기준
        if cell.area == "B" and aisle == "09":
            px = 17  # 세로 진열면의 오른쪽 통로
        if code == "A12-00":
            px = 17
        if cell.area == "C_D" and cell.cx < 1:
            px, py = 1, cell.cy  # 왼쪽 세로 진열면
        depth = rule["depth_offset"] + max(0, rule["depth_sign"] * (px - rule["entry_x"]))
        block = int(np.searchsorted(rule["block_boundaries_x"], px, side="right"))
        side = "up" if py < rule["entry_y"] else "down"
        rows.append({"rack_code": code, "direction": rule["direction"],
                     "depth": depth, "branch": f"{cell.area}:{block}:{side}",
                     "lateral": abs(py - rule["entry_y"]), "pick_x": px, "pick_y": py})
    connector = model["cold_connector"]
    rule = model["areas"]["B"]
    block = int(np.searchsorted(rule["block_boundaries_x"], connector["x"], side="right"))
    side = "up" if connector["y"] < rule["entry_y"] else "down"
    rows.append({"rack_code": "B_TO_A", "direction": "cold",
                 "depth": rule["entry_x"] - connector["x"],
                 "branch": f"B:{block}:{side}",
                 "lateral": abs(connector["y"] - rule["entry_y"]),
                 "pick_x": connector["x"], "pick_y": connector["y"]})
    return pd.DataFrame(rows).set_index("rack_code")


def calculate_order_costs(picks, features, tau=0):
    """최대 깊이 왕복 + 각 블록 위/아래의 최대 측방 진입 왕복. 누락 주문은 순위 제외."""
    assert tau >= 0
    mapped = picks["rack_code"].isin(features.index)
    orders = picks.assign(cost_mapped=mapped).groupby("order_id").agg(
        requested_at=("requested_at", "min"), pick_rows=("rack_code", "size"),
        distinct_racks=("rack_code", "nunique"), mapped_rows=("cost_mapped", "sum"),
        split_count=("split_order_id", "nunique"))
    orders["unmapped_rows"] = orders["pick_rows"] - orders["mapped_rows"]
    orders["complete"] = orders["unmapped_rows"].eq(0)
    visits = picks.loc[mapped, ["order_id", "rack_code"]].drop_duplicates().join(
        features, on="rack_code")
    points = visits
    if "B_TO_A" in features.index:
        cold_orders = visits.loc[visits["rack_code"].str.startswith("A"), "order_id"].unique()
        connectors = pd.DataFrame({"order_id": cold_orders, "rack_code": "B_TO_A"}).join(
            features, on="rack_code")
        points = pd.concat([visits, connectors], ignore_index=True)
    depths = points.groupby(["order_id", "direction"])["depth"].max().unstack(fill_value=0)
    depths = depths.reindex(columns=["ambient", "cold"], fill_value=0)
    branches = points.groupby(["order_id", "branch"])["lateral"].max()
    lateral = 2 * (branches - tau).clip(lower=0).groupby("order_id").sum()
    orders = orders.join(depths.rename(columns={"ambient": "ambient_depth", "cold": "cold_depth"}))
    orders = orders.join(lateral.rename("lateral_cost"))
    components = ["ambient_depth", "cold_depth", "lateral_cost"]
    orders[components] = orders[components].fillna(0)
    orders["depth_cost"] = 2 * (orders["ambient_depth"] + orders["cold_depth"])
    orders["known_rack_cost"] = orders["depth_cost"] + orders["lateral_cost"]
    orders["distance_cost"] = orders["known_rack_cost"].where(orders["complete"])
    orders["cost_rank"] = orders["distance_cost"].rank(method="min", ascending=False)
    return orders, visits


def load_september_picks(root, layout):
    source = root / "outbound_2026-06-01_2026-09-27_2026-09-28_1152.csv"
    with duckdb.connect() as con:
        con.read_csv(str(source), all_varchar=True).create_view("raw")
        picks = con.sql("""
            SELECT "orderId(주문번호)" AS order_id, splitOrderId AS split_order_id,
                   CAST(outboundRequestDateTime AS TIMESTAMP) AS requested_at,
                   locationCode AS location_code, skuCode AS sku_code, skuName AS sku_name,
                   CAST(pickingQuantity AS INTEGER) AS picking_quantity
            FROM raw
            WHERE status = 'SHIPPED' AND CAST(pickingQuantity AS INTEGER) > 0
              AND CAST(outboundRequestDateTime AS TIMESTAMP) >= TIMESTAMP '2026-09-01'
              AND CAST(outboundRequestDateTime AS TIMESTAMP) < TIMESTAMP '2026-10-01'
        """).df()
    assert picks["order_id"].notna().all() and picks["order_id"].str.strip().ne("").all()
    picks["rack_code"] = picks["location_code"].str.extract(r"^([A-Z]\d{2}-\d{2})-\d+$")[0]
    placed = layout.racks.index[layout.racks["observed"]]
    picks["on_map"] = picks["rack_code"].isin(placed)
    return picks


def count_visits(picks, layout):
    """상품 수량·층·선반·분할 출고에 관계없이 주문-렉 쌍을 한 번 센다."""
    visits = picks.loc[picks["on_map"], ["order_id", "rack_code"]].drop_duplicates()
    counts = visits.groupby("rack_code").size().rename("order_visits")
    racks = layout.racks.loc[layout.racks["observed"]].join(counts)
    racks["order_visits"] = racks["order_visits"].fillna(0).astype(int)
    racks["order_share_pct"] = 100 * racks["order_visits"] / picks["order_id"].nunique()
    return racks


def configure_plot():
    fonts = {font.name for font in font_manager.fontManager.ttflist}
    for font in ("AppleGothic", "Malgun Gothic", "NanumGothic"):
        if font in fonts:
            plt.rcParams["font.family"] = font
            break
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.facecolor"] = "#f8fafc"


def draw_layout(layout, values, title, subtitle, output, selected=None, model=None):
    """빈도 지도에 선택 주문의 렉을 표시한다. 실제 이동 경로는 그리지 않는다."""
    configure_plot()
    selected = set() if selected is None else set(selected)
    norm = Normalize(vmin=0, vmax=max(1, values.max()))
    cmap = plt.get_cmap("Reds")
    fig, axes = plt.subplots(1, 3, figsize=(24, 12), layout="constrained",
                             width_ratios=[g.shape[1] for g in layout.grids.values()])
    for ax, (area, grid) in zip(axes, layout.grids.items()):
        background = np.where(np.isin(grid, list(".#")), 0, 1)
        ax.imshow(background, cmap=ListedColormap(["#ffffff", "#e7e5e4"]),
                  vmin=0, vmax=1, interpolation="nearest")
        for row, col in zip(*np.nonzero(grid == "#")):
            ax.add_patch(Rectangle((col - .5, row - .5), 1, 1, facecolor="#d6d3d1",
                                   edgecolor="#57534e", hatch="xxx", linewidth=.5))
        cells = layout.racks.loc[layout.racks["area"].eq(area)]
        for code, cell in cells.iterrows():
            value = values.get(code, 0)
            face = cmap(norm(value)) if value else "#ffffff"
            ax.add_patch(Rectangle((cell.x, cell.y), cell.width, cell.height,
                                   facecolor=face, edgecolor="#94a3b8", linewidth=.45,
                                   hatch=None if cell.observed else "//"))
            if cell.observed:
                ax.text(cell.cx, cell.cy, f"{code[:3]}\n{code[4:]}", ha="center",
                        va="center", fontsize=5.6,
                        color="white" if norm(value) > .6 else "#334155")
            if code in selected:
                ax.add_patch(Rectangle((cell.x, cell.y), cell.width, cell.height,
                                       fill=False, edgecolor="#0284c7", linewidth=2.3))
                ax.scatter(cell.x + cell.width * .85, cell.y + cell.height * .2,
                           s=24, facecolor="#0ea5e9", edgecolor="white",
                           linewidth=.9, zorder=4)
        number = len(selected.intersection(cells.index))
        suffix = f" · 선택 주문 방문 {number}개" if selected else ""
        ax.set_title(TITLES[area] + suffix, fontsize=14)
        ax.set(xlim=(-.5, grid.shape[1] - .5), ylim=(grid.shape[0] - .5, -.5),
               xlabel="도면별 독립 상대 좌표")
        if model is not None:
            rule = model["areas"][area]
            ax.scatter(rule["entry_x"], rule["entry_y"], marker="*", s=110,
                       color="#16a34a", edgecolor="white", zorder=5)
            if area == "B":
                p = model["cold_connector"]
                ax.scatter(p["x"], p["y"], marker=">", s=65,
                           color="#7c3aed", edgecolor="white", zorder=5)
    bar = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=axes,
                       location="bottom", shrink=.45, pad=.025)
    bar.set_label("9월 렉별 방문 주문 수(회) · 같은 주문의 같은 렉은 1회 · 전체 도면 동일 척도")
    legend = "빨강 = 전체 주문의 할당 렉 방문 빈도"
    if selected:
        legend += " · 파랑 = 선택 주문의 방문 렉"
    if model is not None:
        legend += "\n초록 별 = 구역별 진입 대표점 · 보라 삼각형 = B→A 출구 대표점"
    fig.suptitle(f"{title}\n{subtitle}\n{legend} · 실제 경로선 아님",
                 fontsize=15)
    fig.savefig(output, dpi=160, bbox_inches="tight")
    plt.close(fig)


def build_report(root, picks=None):
    """9월 보고서와 재사용할 결과 테이블을 생성한다."""
    from hit_stocks_analysis.mfc_layout import load_layout

    model_path = root / "references/mfc_layout/distance_model_2026-09.json"
    model = json.loads(model_path.read_text(encoding="utf-8"))
    layout = load_layout(model["layout_version"])
    picks = load_september_picks(root, layout) if picks is None else picks
    folder = root / "reports/mfc_order_distance/2026-09"
    folder.mkdir(parents=True, exist_ok=True)
    features = rack_cost_features(layout, model)
    orders, visits = calculate_order_costs(picks, features, tau=model["tau"])
    alternative, _ = calculate_order_costs(picks, features, tau=model["tau_sensitivity"])
    orders["cost_tau2"] = alternative["distance_cost"]
    complete = orders.loc[orders["complete"]].copy()
    complete["mean_gap"] = (complete["distance_cost"] - complete["distance_cost"].mean()).abs()
    ranked = complete.reset_index().sort_values(
        ["distance_cost", "requested_at", "order_id"], ascending=[False, True, True])
    mean_order = complete.reset_index().sort_values(["mean_gap", "requested_at", "order_id"])
    mean_orders = mean_order.head(10).copy()
    mean_orders.insert(0, "representative_rank", range(1, len(mean_orders) + 1))
    rack_lists = visits.groupby("order_id")["rack_code"].agg(lambda s: ", ".join(sorted(s)))
    mean_orders["rack_codes"] = mean_orders["order_id"].map(rack_lists)
    longest_id, mean_id = ranked.iloc[0]["order_id"], mean_order.iloc[0]["order_id"]
    max_cost = complete["distance_cost"].max()
    longest_ids = complete.index[np.isclose(complete["distance_cost"], max_cost)].tolist()
    counts = count_visits(picks, layout)
    unknown = (picks.loc[~picks["on_map"]].groupby(["rack_code", "location_code"], dropna=False)
               .agg(pick_rows=("order_id", "size"), orders=("order_id", "nunique")))
    summary = {
        "period": [str(picks["requested_at"].min()), str(picks["requested_at"].max())],
        "orders": len(orders), "complete_orders": len(complete),
        "excluded_orders": int((~orders["complete"]).sum()),
        "pick_rows": len(picks), "mapped_rows": int(picks["on_map"].sum()),
        "mapped_order_rack_visits": int(counts["order_visits"].sum()),
        "mean_cost": float(complete["distance_cost"].mean()),
        "median_cost": float(complete["distance_cost"].median()),
        "max_cost": float(max_cost), "max_order_count": len(longest_ids),
        "max_order_ids": longest_ids, "longest_order_id": longest_id,
        "nearest_mean_order_id": mean_id,
        "nearest_mean_order_ids": mean_orders["order_id"].tolist(),
        "nearest_mean_order_cost": float(complete.at[mean_id, "distance_cost"]),
        "orders_with_multiple_splits": int(orders["split_count"].gt(1).sum()),
        "model": model,
    }
    sensitivity = pd.DataFrame([
        {"tau": tau, "orders": int(frame["complete"].sum()),
         "mean_cost": frame["distance_cost"].mean(),
         "max_cost": frame["distance_cost"].max(),
         "max_order_id": frame["distance_cost"].idxmax()}
        for tau, frame in ((model["tau"], orders), (model["tau_sensitivity"], alternative))
    ])
    for name, table in {"order_costs": orders, "rack_visits": counts,
                        "rack_cost_features": features, "unmapped_locations": unknown,
                        "top20_orders": ranked.head(20).set_index("order_id")}.items():
        table.to_csv(folder / f"{name}.csv", encoding="utf-8-sig")
    sensitivity.to_csv(folder / "sensitivity.csv", index=False, encoding="utf-8-sig")
    mean_orders.to_csv(folder / "mean_representative_orders.csv", index=False,
                       encoding="utf-8-sig")
    (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    draw_layout(layout, counts["order_visits"], "9월 렉 방문 빈도",
                f"2026-09-01~09-27 · 전체 {len(orders):,}개 주문 · "
                f"지도 표시 {picks['on_map'].mean():.2%} (피킹 행 기준)",
                folder / "rack_visit_heatmap.png", model=model)
    for kind, order_id, label in (("longest", longest_id, "최장 거리 비용 주문"),
                                  ("mean", mean_id, "평균 비용에 가장 가까운 실제 주문")):
        selected = picks.loc[picks["order_id"].eq(order_id)].copy()
        selected = selected.join(features, on="rack_code")
        selected.sort_values(["rack_code", "location_code"]).to_csv(
            folder / f"{kind}_order_locations.csv", index=False, encoding="utf-8-sig")
        row = orders.loc[order_id]
        subtitle = (f"주문 {order_id} · 비용 {row.distance_cost:.2f} = "
                    f"깊이 왕복 {row.depth_cost:.2f} + 측방 왕복 {row.lateral_cost:.2f}\n"
                    f"렉 {row.distinct_racks}개 · 출고 분할 {row.split_count}개 · "
                    f"완전 매핑 주문 평균 {summary['mean_cost']:.2f} · 미보정 상대 비용")
        draw_layout(layout, counts["order_visits"], label, subtitle,
                    folder / f"{kind}_order.png", selected["rack_code"], model)
    mean_folder = folder / "mean_representatives"
    mean_folder.mkdir(exist_ok=True)
    gallery = ["# 평균 거리 비용에 가까운 대표 주문 10개\n",
               f"기준 평균: **{summary['mean_cost']:.6f}** (완전 매핑 주문, τ=0).\n",
               "평균과의 절대 차이 → 요청 시각 → 주문번호 순으로 선정했다. "
               "방문 조합의 다양성을 기준으로 뽑은 표본은 아니다.\n",
               "빨강은 전체 주문의 렉 방문 빈도, 파란 테두리는 해당 주문의 방문 렉이다. "
               "비용은 미보정 상대값이며 실제 거리·경로가 아니다.\n"]
    for row in mean_orders.itertuples(index=False):
        selected = picks.loc[picks["order_id"].eq(row.order_id)]
        name = f"{row.representative_rank:02}_{row.order_id}.png"
        draw_layout(layout, counts["order_visits"],
                    f"평균 거리 대표 주문 {row.representative_rank}/10",
                    f"주문 {row.order_id} · 비용 {row.distance_cost:.2f} · "
                    f"평균과 차이 {row.mean_gap:.6f}\n"
                    f"방문 렉 {row.distinct_racks}개 · 깊이 {row.depth_cost:.2f} + "
                    f"측방 {row.lateral_cost:.2f}",
                    mean_folder / name, selected["rack_code"], model)
        gallery.extend([
            f"## {row.representative_rank}. 주문 {row.order_id}\n",
            f"요청 {row.requested_at} · 비용 {row.distance_cost:.2f} · "
            f"렉 {row.distinct_racks}개 · 평균과 차이 {row.mean_gap:.6f}\n",
            f"![주문 {row.order_id} 방문 위치](mean_representatives/{name})\n",
            f"방문 렉: {row.rack_codes}.\n",
        ])
    (folder / "mean_representatives.md").write_text("\n".join(gallery), encoding="utf-8")
    selected_picks = picks.loc[picks["order_id"].isin(mean_orders["order_id"])].copy()
    selected_picks = selected_picks.merge(
        mean_orders[["order_id", "representative_rank"]], on="order_id", validate="many_to_one")
    selected_picks.sort_values(["representative_rank", "rack_code", "location_code"]).to_csv(
        folder / "mean_representative_locations.csv", index=False, encoding="utf-8-sig")
    configure_plot()
    fig, ax = plt.subplots(figsize=(12, 5), layout="constrained")
    ax.hist(complete["distance_cost"], bins=50, color="#64748b", edgecolor="white")
    ax.axvline(summary["mean_cost"], color="#0284c7", label=f"평균 {summary['mean_cost']:.2f}")
    ax.axvline(summary["max_cost"], color="#dc2626", label=f"최대 {summary['max_cost']:.2f}")
    ax.set(xlabel="주문별 상대 거리 비용 (τ=0 · 미보정)", ylabel="주문 수",
           title=f"9월 거리 비용 분포 · 완전 매핑 {len(complete):,}개 주문")
    ax.legend()
    fig.savefig(folder / "cost_distribution.png", dpi=160)
    plt.close(fig)
    longest_racks = sorted(visits.loc[visits["order_id"].eq(longest_id), "rack_code"])
    mean_racks = sorted(visits.loc[visits["order_id"].eq(mean_id), "rack_code"])
    report = f"""# 9월 주문별 상대 거리 비용과 렉 방문

기간: {summary['period'][0]} ~ {summary['period'][1]} (9/28~30 자료 없음).
출고 요청 시각 기준, SHIPPED·피킹 수량 양수. 주문 키는 orderId이며 분할 출고는 한 주문으로 묶는다.
실제 작업 횟수·경로·미터·소요시간이 아닌 **할당 렉 기준 미보정 비용**이다.

| 항목 | 결과 |
| --- | ---: |
| 전체 주문 | {len(orders):,} |
| 거리 통계에 포함한 완전 매핑 주문 | {len(complete):,} |
| 위치 누락으로 거리 통계에서 제외 | {summary['excluded_orders']:,} |
| 평균 비용 | {summary['mean_cost']:.2f} |
| 중앙값 | {summary['median_cost']:.2f} |
| 최대 비용 | {max_cost:.2f} |
| 최대 비용 동률 주문 수 | {len(longest_ids)} |

## 렉 방문 빈도

전체 주문의 지도 표시 가능한 주문-렉 쌍 {summary['mapped_order_rack_visits']:,}개를 센다.
같은 주문의 같은 렉은 층·선반·수량과 관계없이 1회다. 색은 실제 방문 횟수의 기록이 아니라
할당 로케이션을 방문한 것으로 보는 주문 수이며, 모든 도면에 동일한 선형 색 척도를 쓴다.
기존 시간대별 보고서의 전체 값은 시간대별 고유 방문의 합이다. 이번 집계는 시간대 경계를
걸친 같은 주문-렉도 월 전체에서 한 번만 센다.
![렉 방문 빈도](rack_visit_heatmap.png)

## 최장 거리 비용 주문

주문 **{longest_id}**, 비용 **{max_cost:.2f}**, 방문 렉 **{len(longest_racks)}개**.
최대 동률 주문: {', '.join(longest_ids)}.

![최장 비용 주문 방문 위치](longest_order.png)

방문 렉: {', '.join(longest_racks)}.

## 평균 비용과 대표 주문

평균은 완전 매핑 {len(complete):,}개 주문 비용의 산술평균이다.
대표 주문 **{mean_id}**의 비용은 **{summary['nearest_mean_order_cost']:.2f}**다.
평균과 차이가 최소인 주문 중 요청 시각·주문번호 순으로 선정했다.
이 주문의 방문 조합이 모든 주문의 평균 위치를 뜻하지는 않는다.

![평균 비용에 가까운 주문 방문 위치](mean_order.png)

방문 렉: {', '.join(mean_racks)}.

[평균 거리 대표 주문 10개와 방문 지도](mean_representatives.md)를 함께 저장했다.
목록과 방문 렉은 `mean_representative_orders.csv`, 상품별 원본 위치는
`mean_representative_locations.csv`에서 확인할 수 있다.

![거리 비용 분포](cost_distribution.png)

## 계산 기준과 한계

`비용 = 2×(상온 최대 깊이 + 냉장·냉동 최대 깊이) + 2×Σ max(0, 블록별 측방 최대 진입−τ)`.
주 이동은 상온에서 오른쪽, 냉장·냉동에서 왼쪽이다. A 방문 시 B 통과 깊이 17칸과
B04 출구 방문을 포함한다. C·D는 같은 도면의 최대 깊이를 사용하므로 C 통과를 중복 합산하지 않는다.
측방은 같은 깊이의 진열 블록별로 위·아래를 나눠 최대 범위를 센다.
**초안의 진입 구간 j를 깊이 블록×위/아래로 근사한 첫 구현**이며, 개별 복도의 S자 경로는 아니다.

입구 대표점은 A=(17,13), B=(17,7), C_D=(1,10), B→A 출구=(0,13)이다.
사용자가 확인한 인접 렉을 바탕으로 선정한 모델 좌표이며 정확한 출입구 좌표로 확인된 값은 아니다.
도면별 1칸을 동일 비용 1로 두고, 패킹↔입구·구역 사이 추가 연결 및 기둥 우회 비용은 0으로 생략했다.
통로상의 피킹 위치는 일반 렉의 x 중심과 복도 중심 y로 근사한다.
블록 안의 반복 진입·실제 관통 경로는 생략하므로 물리적으로 통행 가능한 경로 길이를 보장하지 않는다.
서로 다른 도면 축척과 진입 구간 묶음에 따라 비용·순위가 달라질 수 있다.

기본 τ=0(짧은 이동도 포함). τ=2는 가상 민감도 비교이며 확정된 현장 기준이 아니다.
τ=2 평균은 {sensitivity.iloc[1]['mean_cost']:.2f}, 최대는 {sensitivity.iloc[1]['max_cost']:.2f}다.
M·S 코드 및 C08-00 등 위치 누락 주문은 평균·순위에서 제외하며, CSV의 known_rack_cost는
위치가 알려진 렉만의 부분 비용으로 보존한다. 전체 주문의 실제 최장이라고 단정할 수 없다.
분할 출고 {summary['orders_with_multiple_splits']:,}개 주문은 고객 주문 단위로 묶었으며
분할마다 별도 왕복하는 비용은 계산하지 않았다.

## 파일

- `order_costs.csv`: 전체 주문의 비용 분해·누락·순위·τ=2 비교.
- `rack_visits.csv`: 렉별 방문 주문 수·전체 주문 중 비율·좌표.
- `longest_order_locations.csv`, `mean_order_locations.csv`: 선택 주문의 렉·원본 로케이션·상품.
- `rack_cost_features.csv`: 렉별 깊이·측방·진입 구간 및 B_TO_A 연결점.
- `unmapped_locations.csv`, `top20_orders.csv`, `sensitivity.csv`, `summary.json`.

모델 설정: `references/mfc_layout/distance_model_2026-09.json`.
재실행: 프로젝트 루트에서 `./scripts/uv run python scripts/analyze_mfc_order_distance.py`.
"""
    (folder / "summary.md").write_text(report, encoding="utf-8")
    return {"summary": summary, "orders": orders, "visits": visits, "picks": picks,
            "mean_orders": mean_orders,
            "counts": counts, "features": features, "sensitivity": sensitivity,
            "layout": layout, "folder": folder}
