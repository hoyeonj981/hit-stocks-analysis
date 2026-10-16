"""설치, 실제 CSV 읽기, Parquet 왕복, 그래프 생성을 확인합니다."""

import importlib
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import matplotlib
import pandas as pd

from hit_stocks_analysis import list_outbound_files, load_sample

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def main() -> None:
    print(f"Python {sys.version.split()[0]}")
    for name in (
        "pandas",
        "numpy",
        "matplotlib",
        "seaborn",
        "scipy",
        "sklearn",
        "duckdb",
        "pyarrow",
        "openpyxl",
        "jupyterlab",
        "ipykernel",
    ):
        module = importlib.import_module(name)
        print(f"  {name}: {module.__version__}")

    files = list_outbound_files()
    for path in files:
        sample = load_sample(path, nrows=100)
        assert not sample.empty, f"빈 CSV: {path.name}"
        assert isinstance(sample["skuCode"].dtype, pd.StringDtype)
    print(f"CSV {len(files)}개 표본 읽기 및 SKU 문자열 보존: OK")

    with duckdb.connect(":memory:") as connection:
        relation = connection.read_csv(
            [str(path) for path in files], header=True, all_varchar=True, union_by_name=True
        )
        assert len(relation.limit(5).df()) == 5
    print("DuckDB 다중 CSV 조회: OK")

    with TemporaryDirectory() as temporary:
        output = Path(temporary)
        sample.to_parquet(output / "sample.parquet", index=False)
        pd.testing.assert_frame_equal(sample, pd.read_parquet(output / "sample.parquet"))
        figure, axes = plt.subplots()
        axes.plot([1, 2, 3], [1, 4, 9])
        figure.savefig(output / "plot.png")
        plt.close(figure)
        assert (output / "plot.png").stat().st_size > 0
    print("Parquet 왕복 및 PNG 생성: OK")


if __name__ == "__main__":
    main()
