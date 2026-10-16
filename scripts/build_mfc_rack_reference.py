"""2026년 9월 출고에서 지도 스케일 조정용 렉 목록을 추출한다.

실행: ./scripts/uv run python scripts/build_mfc_rack_reference.py
출고에서 관측한 코드 목록이며 전체 렉 마스터나 좌표표가 아니다.
"""

import json

import pandas as pd

from hit_stocks_analysis import find_project_root


def main():
    root = find_project_root()
    source = root / "outbound_2026-06-01_2026-09-27_2026-09-28_1152.csv"
    output = root / "reports/mfc_layout"
    output.mkdir(parents=True, exist_ok=True)
    columns = ["outboundRequestDateTime", "locationCode", "status"]
    parts = []
    for chunk in pd.read_csv(source, usecols=columns, dtype="string", chunksize=200_000):
        dates = pd.to_datetime(chunk["outboundRequestDateTime"], errors="raise")
        selected = dates.ge("2026-09-01") & dates.lt("2026-10-01")
        parts.append(chunk.loc[selected & chunk["status"].eq("SHIPPED")].copy())
    data = pd.concat(parts, ignore_index=True)
    codes = data["locationCode"].str.extract(
        r"^(?P<zone>[ABCD])(?P<aisle>\d{2})-(?P<rack>\d{2})-\d+$"
    )
    valid = codes.notna().all(axis=1)
    racks = (
        codes.loc[valid].groupby(["zone", "aisle", "rack"]).size()
        .rename("outbound_rows").reset_index()
    )
    racks["rack_code"] = racks["zone"] + racks["aisle"] + "-" + racks["rack"]
    racks.to_csv(output / "rack_reference_2026_09.csv", index=False)
    summaries = []
    for (zone, aisle), group in racks.groupby(["zone", "aisle"]):
        observed = set(group["rack"].astype(int))
        missing = sorted(set(range(min(observed), max(observed) + 1)) - observed)
        summaries.append({
            "zone": zone, "aisle": aisle, "observed_rack_count": len(observed),
            "observed_racks": ",".join(group["rack"]),
            "unobserved_between_min_max": ",".join(f"{n:02}" for n in missing),
        })
    pd.DataFrame(summaries).to_csv(output / "aisle_reference_2026_09.csv", index=False)
    excluded = data.loc[~valid, "locationCode"].fillna("<missing>").value_counts()
    excluded.rename_axis("location_code").rename("outbound_rows").to_csv(
        output / "excluded_locations_2026_09.csv"
    )
    metadata = {
        "source": source.name,
        "date_column": "outboundRequestDateTime",
        "first_observed_request": data["outboundRequestDateTime"].min(),
        "last_observed_request": data["outboundRequestDateTime"].max(),
        "shipped_rows": len(data), "mapped_zone_rows": int(valid.sum()),
        "excluded_rows": int((~valid).sum()), "observed_racks": len(racks),
        "note": "9월 1~27일 관측 자료. 미관측 번호는 렉 부재를 뜻하지 않음.",
    }
    (output / "rack_reference_2026_09.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
