"""원본 CSV를 변경하지 않고 작은 표본부터 불러옵니다."""

from pathlib import Path

import pandas as pd

ID_COLUMNS = ("splitOrderId", "orderId(주문번호)", "skuCode", "locationCode")


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "src" / "hit_stocks_analysis"
        ).is_dir():
            return candidate
    raise FileNotFoundError("프로젝트 폴더 또는 notebooks 폴더에서 실행하세요.")


def list_outbound_files(root: Path | None = None) -> list[Path]:
    files = sorted((root or find_project_root()).glob("outbound_*.csv"))
    if not files:
        raise FileNotFoundError("프로젝트 루트에 outbound_*.csv 파일이 없습니다.")
    return files


def load_sample(path: Path | None = None, nrows: int = 10_000) -> pd.DataFrame:
    """첫 파일의 앞부분을 읽습니다. 무작위/대표 표본이 아닙니다."""
    if nrows < 1:
        raise ValueError("nrows는 1 이상이어야 합니다.")
    source = path if path is not None else list_outbound_files()[0]
    return pd.read_csv(
        source,
        encoding="utf-8-sig",
        dtype=dict.fromkeys(ID_COLUMNS, "string"),
        nrows=nrows,
    )
