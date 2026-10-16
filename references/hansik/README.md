# 한식 조리 재료 선별 기준

대상은 **2025년 원본 파일에 등장하는 전체 SKU**입니다. 시간대별 상위 상품에
한정하지 않습니다. 2024년·2026년 상품은 이번 분석 기간 밖입니다.

## 근거와 적용 범위

`sources.json`에 공개 자료 15건의 발행처·URL·확인일을 기록했습니다.
`ingredient_rules.csv`에는 92개 재료군의 출처 ID, 근거 요약, 상품명 연결 정규식을
기록했습니다. Korea.net의 한국전통음식연구소 협력 레시피, Culinary Institute of
America의 한국 요리 자료, 한식 요리 저자 Maangchi의 식재료 목록·레시피를 참고했습니다.

- [Korea.net 된장찌개](https://www.korea.net/NewsFocus/Culture/view?articleId=144788)
- [CIA World Culinary Arts: Korea](https://ciaprochef.com/wp-content/uploads/2024/04/WCA_Korea_Recipes.pdf)
- [Maangchi Korean cooking ingredients](https://www.maangchi.com/ingredients)

자료는 **해당 재료가 한식 조리에 쓰인다는 근거**입니다. 개별 SKU를 한식으로
인증하는 자료는 아닙니다. 품종·부위·손질 형태를 재료군에 연결하는 규칙과 완제품
제외 규칙은 이 프로젝트에서 작성한 휴리스틱입니다. 실제 주문자가 한식을
만들었는지, 한식에만 쓰이는 재료인지는 이 데이터로 알 수 없습니다.

포함 범위는 채소·버섯·육류·달걀·수산물·곡물·기본 양념과 조리용 두부·어묵·떡·면입니다.
김치·양념육·즉석국·밀키트·반찬·간식·음료·복합 소스는 재료 중심 분석에서 제외합니다.
기본 참치 통조림·건어물·자숙 새우처럼 다시 요리하는 재료는 포함할 수 있습니다.
원물만을 뜻하는 분류는 아닙니다.

## 분류 상태

| 값 | 의미 |
|---|---|
| included | 근거 사전과 연결되고 상품명 형태 규칙을 통과한 재료 후보 |
| review | 연결된 재료가 있으나 혼합·조리 여부, 상품명 또는 동일 SKU의 명칭 변형 확인 필요 |
| excluded_form | 완제품·음료·비식품 등의 제외 규칙에 해당 |
| not_matched | 현재 근거 사전과 연결하지 못함; 비한식 확정이 아님 |

상품명 마지막 재료 표현을 대표 재료로 택하고, 뒤의 용량·단순 손질 표현 및
완제품 표현을 검사합니다. `양지뜨레 대란`, `자갈치`, `고추장 삼겹살` 같은 오탐
사례를 별도 검사합니다. 선택된 대표 재료는 원재료 전체 목록이 아닙니다.
근거 사전은 모든 한식 재료를 망라하지 않으며, 상품명만으로 판단하므로 오탐·누락이
남을 수 있습니다. `review`와 `not_matched`도 보존하므로 다음 검토에 활용할 수 있습니다.

## 결과 파일과 재현

`./scripts/uv run --locked python scripts/build_hansik_2025.py` 또는
`notebooks/03_hansik_ingredients_2025.ipynb`의 전체 셀을 실행합니다.
결과 생성은 저장된 근거표를 사용하며 인터넷 연결이 필요하지 않습니다.
실행하면 아래 생성 파일을 갱신합니다. 원본 CSV와 기존 전체상품 분석 결과는 보존됩니다.

`data/hansik_2025/`:

- `products.csv` / `.parquet`: 선별 SKU, 연간 고유 주문 수·피킹 수량·출고 행 수, 분류 근거 URL
- `outbound_ingredients.parquet`: 선별 상품의 유효 출고 행. 원본 12개 열과 분석용 열·근거 정보
- `classification_audit.csv`: 전체 SKU의 분류, 제외·검토 사유와 연결된 근거
- `review_products.csv`, `unmatched_products.csv`: 추가 확인할 상품
- `ingredient_rules.csv`, `sources.csv`: 생성 시 사용한 근거표 사본

`reports/hansik_2025/`에는 시간별 전체 순위·TOP 10·시간별 주문 수 CSV,
`hansik_ingredients_2025.xlsx`, 집계·검증 요약 `summary.json`을 저장합니다.

상품 마스터는 SKU당 1행입니다. 근거가 여러 개여도 출고 행을 늘리지 않습니다.
원본 `SHIPPED`, 양의 `pickingQuantity`, 유효 주문번호·SKU, 2025년 요청 시각인 행을
사용합니다. 연간 주문 수는 SKU별 고유 주문번호 수이며, 시간별 주문 수 합과 다를 수 있습니다.
수량은 단위가 다른 상품의 피킹 수량 합계로, 중량이나 매출이 아닙니다.

시간은 **출고 요청 시각**이고 실제 출고 완료 시각이 아닙니다. 원본에 시간대 정보가 없어
시차 변환을 하지 않았습니다. 2025-08-31 자료가 없어 364일분이며 이를 무출고로 간주하지 않습니다.
시간별 비중의 분모는 **선별된 재료를 하나 이상 포함한 해당 시간대 고유 주문 수**입니다.
전체 상품 분석의 분모와 다르며, 상품별 비중의 합은 100%를 넘을 수 있습니다.

`rule_ids → ingredient_rules.csv → source_ids → sources.json`으로 출처를 추적합니다.
제외·미연결 상품의 근거 열은 검색된 재료의 근거일 뿐, 제외 판단의 외부 인증이 아닙니다.
CSV는 Excel에서 한글이 보이도록 UTF-8 BOM으로 저장했습니다.
