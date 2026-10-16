# 출고 데이터 분석 환경

Python 3.12, JupyterLab, pandas 기반 분석 프로젝트입니다. 원본 `outbound_*.csv`는 프로젝트 루트에서 읽습니다.

## 시작하기 (macOS / Linux)

이미 설치된 환경에서는 다음 명령으로 JupyterLab을 시작합니다.

```sh
./scripts/lab.sh
```

터미널에 표시되는 `http://127.0.0.1:8888/lab?token=...` 주소를 브라우저에서 열고
`notebooks/01_getting_started.ipynb`를 선택하세요. 커널은 `Python (hit-stocks-analysis)`입니다.
종료하려면 터미널에서 Ctrl+C를 누르세요.

새 환경에서 최초 설치하거나 잠금 파일에 맞춰 복원할 때:

```sh
./scripts/setup.sh
```

설치에는 인터넷 연결과 기본 `python3`가 필요합니다. 설치 스크립트는 프로젝트의 `.tools/`에
uv와 Python 3.12를 준비하고 `.venv/`에 패키지를 설치합니다. 셸 설정이나 시스템 Python은 수정하지 않습니다.
프로젝트를 다른 경로로 옮기면 기존 `.venv/`, `.tools/`를 제거한 뒤 다시 설치하세요.

## 포함된 도구

| 용도 | 패키지 |
| --- | --- |
| 표·수치 계산 | pandas, NumPy |
| 대용량 CSV SQL 분석, Parquet | DuckDB, PyArrow |
| 시각화 | Matplotlib, Seaborn |
| 통계·머신러닝 | SciPy, scikit-learn |
| Excel 입출력 | openpyxl |
| 노트북 | JupyterLab, ipykernel |
| 코드 정리·검사 | Ruff |

## 폴더와 데이터 사용

- `notebooks/`: 분석 노트북
- `src/hit_stocks_analysis/`: 공통 데이터 로딩 함수
- `data/`: 전처리 결과, Parquet 등 파생 데이터
- `reports/`: 표·그래프 등 분석 결과
- `pyproject.toml`, `uv.lock`: 의존성 선언과 설치 버전 잠금

현재 CSV 6개는 합계 약 662MB입니다. 시작 노트북은 첫 파일의 앞 10,000행만 pandas로 읽습니다.
이 표본은 전체 기간을 대표하지 않습니다. ID/코드는 문자열로 읽어 선행 0을 보존합니다.
날짜와 수량의 업무상 의미, 결측치 처리는 실제 분석 단계에서 확인하세요.
전체 데이터를 다룰 때는 DuckDB로 필요한 열과 집계 결과부터 읽는 예제를 참고하세요.

원본 CSV, 파생 데이터, 분석 결과, 가상환경과 캐시는 `.gitignore`에 포함됩니다.
노트북 셀 출력에는 데이터가 포함될 수 있으므로 공유하기 전 출력을 지우세요.

## 실행·관리

```sh
# 패키지 추가 (pyproject.toml과 uv.lock 함께 갱신)
./scripts/uv add 패키지이름

# Python 스크립트 실행
./scripts/uv run python scripts/check_environment.py

# 코드 검사
./scripts/uv run ruff check .
```

VS Code에서는 권장 Python/Jupyter 확장을 설치하고 `.venv/bin/python`을 인터프리터로 선택하세요.
일반 터미널에서도 `source .venv/bin/activate`로 환경을 활성화할 수 있습니다.
Jupyter와 Matplotlib의 캐시를 프로젝트 안에 유지하려면 `./scripts/uv run ...`을 사용하세요.

의존성 관리 방식은 [uv 공식 프로젝트 문서](https://docs.astral.sh/uv/guides/projects/)를 따릅니다.

## 2025년 시간대별 인기 출고 상품

JupyterLab에서 `notebooks/02_hourly_products_2025.ipynb`를 열고
커널 **Python (hit-stocks-analysis)**을 선택한 뒤 **Restart Kernel and Run All Cells**를
실행하세요. CSV 로딩, 집계, 데이터 점검, 시간별 순위, 히트맵, 결과 저장을 셀별로 확인할 수 있습니다.
`HOUR`를 바꾸면 관심 시간대의 TOP 10을 볼 수 있고, `TOP_N`은 전체 시간대 표의 표시 개수입니다.
마지막 셀은 `reports/hourly_2025/`의 기존 결과 파일을 갱신합니다.

터미널에서 노트북을 실행하고 결과를 노트북에 저장하려면:

```sh
./scripts/uv run jupyter nbconvert --to notebook --execute --inplace \
  notebooks/02_hourly_products_2025.ipynb --ExecutePreprocessor.timeout=300
```

기존 스크립트로도 같은 집계를 실행할 수 있습니다.

```sh
./scripts/uv run python scripts/analyze_hourly_2025.py
```

`reports/hourly_2025/`에 시간별 TOP 10·전체 순위 CSV, Excel, 요약 Markdown,
주문 빈도 히트맵과 데이터 점검 JSON이 저장됩니다.

시간은 **출고 요청 시각**(`outboundRequestDateTime`)의 0–23시이며, 실제 출고 완료 시각은
제공되지 않았습니다. 원본 시간대 정보가 없어 시차 변환을 하지 않습니다.
`SHIPPED` 중 피킹 수량이 양수인 행을 대상으로, 시간대·SKU별 고유 주문번호 수로 순위를
정합니다. 같은 주문의 분할 행은 한 건으로 세고, 피킹 수량은 합산합니다.
빈도 동률은 피킹 수량 내림차순, SKU 오름차순으로 정렬합니다.

현재 2025년 파일에는 **8월 31일 자료가 없어 364일분**입니다. 이 날짜를 무출고로 간주하지 않습니다.
시간별 전체 주문 수는 여러 상품을 담은 주문도 한 건으로 계산하므로, 상품별 주문 수의 합과 다릅니다.

집계 검증: `./scripts/uv run python -m unittest discover -s tests -v`

## 2025년 한식 조리 재료 데이터셋

`notebooks/03_hansik_ingredients_2025.ipynb`에서 전체 셀을 실행하면, 전체 SKU를
공개 자료에 연결해 재료 후보를 선별하고 출고 데이터와 시간대별 순위를 다시 생성합니다.
기본 양념과 두부·어묵 등 조리 재료는 포함하고 완성 요리·반찬·간식은 제외합니다.
상품명만으로 불명확한 항목과 근거 미연결 상품은 별도 목록에 보존합니다.

```sh
./scripts/uv run --locked python scripts/build_hansik_2025.py
```

데이터는 `data/hansik_2025/`, Excel과 시간별 결과는 `reports/hansik_2025/`에 저장합니다.
근거 출처, 분류 한계, 파일별 설명은 [선별 기준](references/hansik/README.md)을 확인하세요.

노트북의 **4-1. 연간 TOP 15 상품의 시간대별 주문 히트맵** 셀은 연간 고유 주문 수
상위 15개 SKU의 0–23시 주문 건수를 표시합니다. `reports/hansik_2025/`에
`hansik_top15_hourly_heatmap.png`와 같은 이름의 CSV를 저장하고,
Excel의 `TOP15_히트맵` 시트에 수치 표와 그래프를 추가합니다.
데이터 구축 스크립트만 재실행하면 Excel이 새로 생성되므로 히트맵 셀도 다시 실행하세요.

## 2026년 분기별 한식 재료 TOP 15 히트맵

`notebooks/04_hansik_ingredients_2026_quarterly.ipynb`를 전체 실행하면 2026년 전체 SKU에
같은 재료 선별 기준을 적용하고, 달력 분기별 고유 주문 수 TOP 15를 각각 선정합니다.
0–23시 고유 주문 건수를 공통 색상 눈금으로 표시하며, 자료가 없는 분기의 그래프는 만들지 않습니다.

```sh
./scripts/uv run --locked python scripts/analyze_quarterly_2026.py
```

`reports/hansik_2026/`에 분기별 PNG·CSV와
`hansik_ingredients_2026_quarterly.xlsx`를 저장합니다. Excel에는 자료 범위, 분기별 TOP 15,
전체 상품의 분기·시간대 집계 및 각 분기의 히트맵 수치 표·이미지가 있습니다.
선별 출고 행과 전체 SKU 분류 내역은 `data/hansik_2026/`에 저장합니다.
2025년 결과는 갱신하지 않습니다.

현재 원본은 2026-01-01부터 2026-09-27까지입니다. 3분기는 일부 기간이며 4분기는
자료가 없습니다. `quarterly_coverage.csv`에서 분기별 관측 날짜 수·미관측 날짜를 확인할 수 있습니다.
히트맵은 일평균이 아닌 누적 건수이며, 분기별 상품 구성과 관측 일수가 다를 수 있습니다.

## 2025년 분기별 한식 재료 TOP 15 히트맵

`notebooks/05_hansik_ingredients_2025_quarterly.ipynb`는 기존 2025년 한식 재료
데이터셋을 재사용하여 분기마다 고유 주문 수 TOP 15를 새로 선정합니다.
연간 분석의 상품 목록을 그대로 TOP 15로 사용하지 않습니다.

```sh
./scripts/uv run --locked python scripts/analyze_quarterly_2025.py
```

`reports/hansik_2025/`에 1–4분기 PNG·CSV와
`hansik_ingredients_2025_quarterly.xlsx`를 저장합니다. 기존 연간 Excel·히트맵과
재료 데이터는 보존합니다. 선행 데이터가 없다면 `03_hansik_ingredients_2025.ipynb`를
먼저 실행하세요.

색상 눈금은 2025년 네 분기에 공통으로 적용합니다. 각 칸은 출고 요청 시각별
누적 고유 주문 건수이며, **3분기의 2025-08-31 자료가 없습니다**.
분기별 관측 일수는 90·91·91·92일로, 일평균을 나타내는 그래프가 아닙니다.

## 2025·2026년 냉장 입고 TOP 15와 월별 비교

- `notebooks/06_inbound_refrigerated_2025.ipynb`: 2025년 전체 기간
- `notebooks/07_inbound_refrigerated_2026.ipynb`: 2026년 제공 기간(현재 1월 1일–10월 11일)

각 노트북에서 전체 셀을 실행하면 해당 연도의 `inbound_*.csv`를 읽고,
`storageMethod == REFRIGERATION`인 상품의 양수 `receivingQuantity` 합계로
TOP 15 SKU를 선정합니다. 부분 입고 수량과 유통기한별 분할 행을 포함합니다.
월 구분은 실제 입고 완료일이 아닌 `shippingScheduledDate`(예정일) 기준이며,
수량은 포장 규격을 환산하지 않은 원본 상품 단위입니다.

고정된 TOP 15의 월별 수량·전월 대비 증감 히트맵과 관측일당 평균 추이를 제공합니다.
2026년 10월은 부분 집계로 표시하고 전월 증감 비교에서 제외합니다.
미관측 월은 0으로 채우지 않습니다. 증감률은 전월 수량이 0이면 계산하지 않습니다.
`reports/inbound_refrigerated_2025/`, `reports/inbound_refrigerated_2026/`에
TOP 15, 월별 수량·증감·증감률·일평균·자료 범위 CSV, Excel 및 그래프 PNG를 저장합니다.

```sh
./scripts/uv run --locked jupyter nbconvert --to notebook --execute --inplace \
  notebooks/06_inbound_refrigerated_2025.ipynb \
  notebooks/07_inbound_refrigerated_2026.ipynb --ExecutePreprocessor.timeout=300
```

## 센터 레이아웃 표시

`notebooks/08_mfc_layout.ipynb`를 전체 실행하면 구역 관계도와 사진 기반 렉 배치 초안을
`reports/mfc_layout/zone_overview.png`, `reports/mfc_layout/rack_layout.png`로 저장합니다.
추가 상온 사진의 긴 D 구역을 반영했으며, 상온 확대 그림은 `ambient_layout.png`로 저장합니다.
`GRID_TEXT`의 상대 격자를 편집하고, 확인한 존·복도·렉 코드는 `RACK_LABELS`에 입력합니다.
1~4절은 기존 배치 초안이며 원본 입출고 데이터를 읽지 않습니다. 층·선반과 동선 계산은 제외합니다.
초안의 크기는 현재 `GRID_TEXT`를 따릅니다. 스케일 지도는 아래 5절에서 생성합니다.
히트맵 정보는 레이아웃 확정 후 반영하며 현재 상온 렉은 같은 색으로 표시합니다.
개별 렉 번호는 미확정이며 실제 축척의 지도가 아닙니다.
상세한 표현 범위는 [레이아웃 설명](docs/mfc_layout_array.md)을 참고하세요.

같은 노트북의 **5절**은 2026년 9월 1~27일 출고 로케이션을 참고해
알파벳 칸 하나에 렉 코드 하나를 연결합니다. 결과는 `rack_scaled_layout.png`,
`ambient_scaled_layout.png`, `scaled_rack_cells.csv`, `scaled_layout_arrays.npz`입니다.
기존 통로·기둥을 보존하고 렉 영역 안을 비례 분할한 초안이며, 개별 경계는 근사입니다.
위치 미확인인 B08-00·C08-00은 `unplaced_racks.csv`에 따로 남깁니다.
6절에서는 냉동·냉장 확대 지도를 `frozen_scaled_layout.png`,
`refrigerated_scaled_layout.png`로 각각 저장합니다.
