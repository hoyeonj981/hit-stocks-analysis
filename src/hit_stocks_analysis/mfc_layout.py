"""기존 통로·기둥 영역을 보존하면서 렉 영역을 코드별 상대 칸으로 나눈다.

복도 방향과 홀짝은 사용자 확인값이다. 연속 구간에 대한 코드 배분·칸 너비는
기존 길이 비율에 따른 근사이며 실제 렉 경계나 이동 경로를 확정하지 않는다.
"""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

LAYOUT_DIR = Path(__file__).resolve().parents[2] / "references" / "mfc_layout"

# 사진 기반 상대 격자. . 통로·교차로, # 기둥, ? 도면 밖, U 용도 미확인,
# A·B·C·D 존 렉 영역, R 상온의 존 미지정 렉 영역. 각 도면의 좌표는 서로 독립이다.
GRID_TEXT = {
    "A": """
??????...AAAAAAA#.
??????..........#.
??????...AAAA...A.
??????...AAAA.....
??????............
??????...AAAA#....
??????...AAAA#....
??????............
??????...AAAA.....
AAAAAA...AAAA.....
..................
.AAAA....AAAA.....
.AAAA....AAAA.....
..................
.AAAA....AAAA.....
.AAAA....AAAA.....
..................
.AAAA....AAAA....
.AAAA....AAAAA....
..................
.AA#A....AAAA....
..................
.AAAA....AAAA.....
.AA#A....AAAAA....
...#..............
.AA#A....AAAAA????
.AAAA....?????????
.........?????????
.AA#A....?????????
.AA#A....?????????
.........?????????
.AAAAAAAA?????????
""",
    "B": """
.BBBBBBBBBBBBBBBB.
................B.
.BBBB....BBBBBB.B.
.BBBB.#..BBBBBB.B.
..................
.BBBB....BBBBBB.B.
.BBBB.#..BBBBBB.B.
................B.
.BBBB.#..BBBBBB.B.
.BBBB.#..BBBBBB...
................B.
.BBBBB...BBBBBB.B.
..BBBB...BBBBBB...
..................
.BBBBBBBB..BBBB...
.BBBBBBBB..???????
...........???????
.BBBBBBBB..???????
.BBBBBBBB..???????
...........???????
.BBBBB.BB..???????
.BBBBB.BB..???????
...........???????
.BBB..BBB..???????
......???????????? 
BBBBBB????????????
""",
    "C_D": """
...CCCCCCCCCCCCCCCDDDDDDDDDDDDDDD.
..................................
...CCCCCC..CCCCC...DDDDD..DD.DD...
...CCCCCC..CCCCC...DDDDD..DD.DD...
..................................
...CCCCCC..CCCCC#..DDDDD..DD.DD...
C..CCCCCC..CCCCC#..DDDDD.#DD.DD...
C.................................
...CCCCCC..CCCCC...DDDDD..DDDDD...
...CCCCCC..CCCCC...DDDDD..DDDDD...
..................................
C..CCCCCC..CCCCC...DDDDD..DDDDD...
C..CCCCCC..CCCCC...DDDDD..DDDDD...
C.................................
C..CCCCCC..CCCCC...DDDDD..DDDDD...
...CCCCCC..CCCCC...DDDDD..DDDDD...
..................................
...CCCCCC..CCCCC...DDDDD..DDDDD..?
...CCCCCC..CCCCC#..DDDDD..DDDDD.??
................#...............??
...CCCCCC..CCCCC#..DDDDD..DDDDD???
...CCCCCC..CCCCC...DDDDD..DDDD????
.............................?????
...CCCCCC..CCCC....DDDDD..DD??????
...CCCCCC..CCCC#...DDDDD..????????
..........................???????? 
.CCCCCCCC..CCCC....DDDDD..????????
""",
}


# 사용자 확인 규칙. 위·아래는 그림 기준이며 실제 방위가 아니다.
ZONE_RULES = {
    "A": {"name": "냉동", "area": "A", "aisle_order": "bottom_to_top",
          "rack_increase": "left_to_right", "upper_face": "even", "lower_face": "odd"},
    "B": {"name": "냉장", "area": "B", "aisle_order": "bottom_to_top",
          "rack_increase": "left_to_right", "upper_face": "even", "lower_face": "odd"},
    "C": {"name": "상온 히트맵", "area": "C_D", "aisle_order": "bottom_to_top",
          "rack_increase": "right_to_left", "upper_face": "odd", "lower_face": "even"},
    "D": {"name": "상온 랜덤", "area": "C_D", "aisle_order": "top_to_bottom",
          "rack_increase": "right_to_left", "upper_face": "odd", "lower_face": "even"},
}
EXCEPTIONS = [
    {"rack_code": "A12-00", "rule": "A 오른쪽 위 ##A 위치의 단독 렉"},
    {"rack_code": "B09-01~06", "rule": "B 오른쪽 입구 근처 세로 렉, 위→아래 01~06"},
    {"rack_code": "B08-00", "rule": "B08-02 바로 왼쪽. 위쪽 짝수 면의 맨 왼쪽"},
    {"rack_code": "D07-01", "rule": "현재 철거됨. 과거 출고 표시를 위해 있는 것으로 처리"},
]
# 일반 면 배치에 넣는 00번 렉. 나머지 00번은 위치 확인 전까지 미배치로 둔다.
CONFIRMED_ZERO_RACKS = {"B08-00"}
# 9월 출고에 없지만 사용자 지시로 지도에 두는 렉. 값은 placement에 기록한다.
ASSUMED_RACKS = {"D07-01": "assumed_removed"}

# 기존 지도 행에서 각 복도의 (위쪽 면, 아래쪽 면).
# A의 20행, B의 23행은 두 복도의 맞닿은 진열면을 한 행에 그린 것으로 근사한다.
FACE_ROWS = {
    "A": {11: (0, 2), 10: (3, 5), 9: (6, 8), 8: (9, 11), 7: (12, 14),
          6: (15, 17), 5: (18, 20), 4: (20, 22), 3: (23, 25),
          2: (26, 28), 1: (29, 31)},
    "B": {aisle: (24 - 3 * aisle, 26 - 3 * aisle) for aisle in range(1, 9)},
    "C": {8 - i: (3 * i, 3 * i + 2) for i in range(9)},
    "D": {i: (3 * i, 3 * i + 2) for i in range(9)},
}
FACE_ROWS["B"][0] = (23, 25)
REVERSE_NUMBERING = {z for z, r in ZONE_RULES.items() if r["rack_increase"] == "right_to_left"}
UPPER_ODD = {z for z, r in ZONE_RULES.items() if r["upper_face"] == "odd"}


def parse_grids(grid_text=GRID_TEXT):
    """GRID_TEXT를 도면별 문자 배열로 바꾼다. 짧은 행의 오른쪽 끝은 ?로 보충한다."""
    grids = {}
    for area, text in grid_text.items():
        rows = [row.rstrip() for row in text.strip().splitlines()]
        width = max(map(len, rows))
        grid = np.array([list(row.ljust(width, "?")) for row in rows])
        assert set(grid.ravel()) <= set("RABCD#.?U")
        grids[area] = grid
    return grids


def check_aisle_order():
    """FACE_ROWS의 복도 배치가 ZONE_RULES의 복도 순서와 맞는지 확인한다."""
    for zone, faces in FACE_ROWS.items():
        aisles = sorted(faces)
        rows = [faces[a][0] for a in aisles]
        upward = ZONE_RULES[zone]["aisle_order"] == "bottom_to_top"
        assert rows == sorted(rows, reverse=upward), f"{zone} 복도 순서 불일치"


def runs(indices):
    """연속한 인덱스를 시작·끝 구간으로 묶는다."""
    groups = []
    for index in indices:
        if groups and groups[-1][1] == index:
            groups[-1] = (groups[-1][0], index + 1)
        else:
            groups.append((index, index + 1))
    return groups


def divide_spans(spans, count):
    """기존 구간 길이 비율로 count칸을 나누며 구간 밖에는 칸을 만들지 않는다."""
    if not count:
        return []
    if not spans:
        raise ValueError("렉 코드에 대응하는 기존 렉 영역이 없습니다.")
    lengths = np.array([end - start for start, end in spans], dtype=float)
    quotas = count * lengths / lengths.sum()
    counts = np.floor(quotas).astype(int)
    for i in np.argsort(-(quotas - counts), kind="stable")[:count - counts.sum()]:
        counts[i] += 1
    cells = []
    for (start, end), n in zip(spans, counts):
        boundaries = np.linspace(start, end, n + 1)
        cells.extend(zip(boundaries[:-1], boundaries[1:]))
    return cells


def scale_racks(layout_arrays, reference):
    """Return code cells, unplaced observed codes, and aisle-label positions.

    한 행은 한 렉 칸이다. x/y는 칸 왼쪽 위, width/height는 상대 너비·높이.
    observed=False는 관측된 같은 면의 번호 사이 미관측 자리이며 실제 렉이 아니다.
    """
    extra = pd.DataFrame([
        {"zone": code[0], "aisle": code[1:3], "rack": code[4:], "rack_code": code}
        for code in ASSUMED_RACKS if code not in set(reference["rack_code"])
    ])
    reference = pd.concat([reference, extra], ignore_index=True)
    reference["aisle"] = reference["aisle"].astype(int)
    reference["rack"] = reference["rack"].astype(int)
    observed = set(reference["rack_code"])
    cells, aisle_positions = [], []

    def add(area, zone, aisle, number, x, y, width, height, method):
        code = f"{zone}{aisle:02}-{number:02}"
        seen = code in observed
        cells.append({
            "area": area, "zone": zone, "aisle": f"{aisle:02}", "rack": f"{number:02}",
            "rack_code": code, "symbol": zone if seen else "~", "observed": seen,
            "x": x, "y": y, "width": width, "height": height,
            "placement": ASSUMED_RACKS.get(code, method),
        })

    for zone, faces in FACE_ROWS.items():
        area = "C_D" if zone in {"C", "D"} else zone
        grid = layout_arrays[area]
        owners = Counter(row for pair in faces.values() for row in pair)
        used = Counter()
        for aisle, (upper, lower) in faces.items():
            aisle_positions.append({"area": area, "zone": zone, "aisle": aisle,
                                    "y": (upper + lower) / 2})
            numbers = reference.loc[
                reference["zone"].eq(zone) & reference["aisle"].eq(aisle)
                & (reference["rack"].gt(0)
                   | reference["rack_code"].isin(CONFIRMED_ZERO_RACKS)), "rack"
            ].tolist()
            for face, row in enumerate((upper, lower)):
                parity = face ^ (zone in UPPER_ODD)
                height = 1 / owners[row]
                y = row - 0.5 + used[row] * height
                used[row] += 1
                face_numbers = [n for n in numbers if n % 2 == parity]
                if not face_numbers:
                    continue
                slots = list(range(min(face_numbers), max(face_numbers) + 1, 2))
                columns = np.flatnonzero(grid[row] == zone).tolist()
                if zone == "A" and row == 2:
                    columns = [x for x in columns if x != 16]  # 별도 A12-00
                if zone == "B" and 1 <= row <= 11:
                    columns = [x for x in columns if x != 16]  # 별도 B09
                spans = [(start - 0.5, end - 0.5) for start, end in runs(columns)]
                divisions = divide_spans(spans, len(slots))
                if zone in REVERSE_NUMBERING:
                    divisions.reverse()
                for number, (start, end) in zip(slots, divisions):
                    add(area, zone, aisle, number, start, y, end - start, height,
                        "proportional_draft")

    # 사용자 확인한 예외. 기존 통로를 채우지 않고 세로 렉 구간만 6칸으로 나눈다.
    grid = layout_arrays["B"]
    rows = [row for row in range(1, 12) if grid[row, 16] == "B"]
    spans = [(start - 0.5, end - 0.5) for start, end in runs(rows)]
    for number, (start, end) in enumerate(divide_spans(spans, 6), start=1):
        add("B", "B", 9, number, 15.5, start, 1, end - start, "vertical_B09")
    assert layout_arrays["A"][2, 16] == "A"
    add("A", "A", 12, 0, 15.5, 1.5, 1, 1, "confirmed_A12")
    result = pd.DataFrame(cells)
    assert result["rack_code"].is_unique
    placed = set(result.loc[result["observed"], "rack_code"])
    pending = reference.loc[~reference["rack_code"].isin(placed)].copy()
    pending["reason"] = "00번 렉의 지도 위치 미확인"
    return result, pending, pd.DataFrame(aisle_positions)


@dataclass
class Layout:
    version: str
    meta: dict
    rules: dict
    grids: dict
    racks: pd.DataFrame
    unplaced: pd.DataFrame


def save_layout(version, grids, cells, unplaced, meta):
    """버전별 레이아웃 스냅샷을 JSON으로 저장한다. 기존 버전 파일은 덮어쓴다."""
    check_aisle_order()
    racks = cells.assign(cx=cells["x"] + cells["width"] / 2,
                         cy=cells["y"] + cells["height"] / 2)
    snapshot = {
        "version": version,
        "meta": meta,
        "rules": ZONE_RULES,
        "exceptions": EXCEPTIONS,
        "face_rows": {z: {f"{a:02}": list(rows) for a, rows in faces.items()}
                      for z, faces in FACE_ROWS.items()},
        "grids": {area: ["".join(row) for row in grid] for area, grid in grids.items()},
        "racks": racks.to_dict(orient="records"),
        "unplaced": unplaced.to_dict(orient="records"),
    }
    LAYOUT_DIR.mkdir(parents=True, exist_ok=True)
    path = LAYOUT_DIR / f"layout_{version}.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    return path


def load_layout(version):
    """저장된 버전을 읽는다. racks는 rack_code 인덱스, cx·cy는 칸 중심 상대 좌표다."""
    data = json.loads((LAYOUT_DIR / f"layout_{version}.json").read_text(encoding="utf-8"))
    racks = pd.DataFrame(data["racks"])
    return Layout(
        version=data["version"], meta=data["meta"],
        rules={"zones": data["rules"], "exceptions": data["exceptions"],
               "face_rows": data["face_rows"]},
        grids={area: np.array([list(row) for row in rows])
               for area, rows in data["grids"].items()},
        racks=racks.set_index("rack_code"),
        unplaced=pd.DataFrame(data["unplaced"]),
    )
