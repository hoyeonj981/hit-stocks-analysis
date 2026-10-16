"""공개 식재료 근거와 명시적 상품명 규칙으로 한식 조리 재료를 선별합니다."""

import json
import re
import unicodedata
from pathlib import Path

import pandas as pd

# 사용자가 지정한 '재료 중심, 완제품 제외' 범위를 구현하는 프로젝트 규칙입니다.
# 이 규칙은 출처 기관의 공식 상품 분류가 아닙니다.
FORM_EXCLUSIONS = {
    "X01_비식품": (
        r"샴푸|린스|치약|칫솔|세제|비누|물티슈|티슈|화장지|강아지|고양이|사료|"
        r"샤워|핸드워시|바디워시|반려동물"
    ),
    "X02_간식음료": (
        r"우유|요거트|요구르트|비요뜨|커피|주스|쥬스|음료|보리차|아이스크림|두유|라떼|프로틴|단백질바|"
        r"칩|과자|스낵|쿠키|크래커|웨하스|파이|케이크|빵|샌드|버거|젤리|푸딩|초코|쵸코|캔디|사탕|"
        r"카라멜|캐러멜|도넛|도너츠|베이글|크루아상|크로와상|크로플|팝콘|콘칲|감자깡|새우깡|맛밤|"
        r"찹쌀떡|인절미|약과|한과|떡바|빙수|호떡|떡갈비|하늘보리|블랙보리|유과|쌀로별|양파링|오징어집|"
        r"(?:생강|대추|도라지|인삼|배)즙|자갈치|꽃보다오징어|아이보리|마가렛트|카스타드|연양갱|"
        r"오예스|말랑카우|크런키|제크|스콘|베이커리|뻥|곡물친구|맘마밀|쉐이크|스프레드|"
        r"눈을감자|초콜릿|밀카|요플레|빈츠|쌀쿵|곡물그대로|앙금|군고구마|스위트고구마|순수고구마"
    ),
    "X03_완성요리": (
        r"김치|반찬|샐러드|볶음밥|햇반|즉석밥|비빔밥|국밥|삼각김밥|주먹밥|덮밥|리조또|밀키트|키트|컵밥|"
        r"라면|사발면|불닭|파스타|스파게티|피자|짜장|짬뽕|마라|카레|우동|돈까스|돈가스|햄버그|함박|"
        r"만두(?!피)|떡볶이(?!떡)|불고기(?!용)|찌개(?!용|두부|와)|전골|갈비탕|곰탕|삼계탕|매운탕|설렁탕|"
        r"추어탕|어묵탕|새우탕|닭볶음탕(?!용)|백숙(?!용)|닭갈비|감자탕|육개장|육개정|순대|치킨|강정|장조림|"
        r"(?:미역|북어|황태|된장|콩나물|어묵|소고기무|해장)국|쌈무|단무지|장아찌|자반|누룽지|죽(?=\s|\d|$)|"
        r"닭개장|강된장|비빔|칠리|크리스피|후라이드|프라이드|커리|쫄면|치볶|컵오트밀|오뚜기밥|"
        r"강남밥상|정미경키친|반하는밥상|(?:새우|전복|꼬막)장|마파두부|그레인보우|쌀국시|완당면"
    ),
    "X04_조미가열완제품": (
        r"양념|시즈닝|훈제|훈연|숯불|바베큐|바비큐|수비드|버터|치즈|베이컨|소시지|소세지|프랑크|비엔나|스팸|리챔|햄|너겟|꿔바로우|"
        r"구운|삶은|직화|오븐|조미|구웠|구워|군밤|군고구마|반숙|감동란|찜질방|"
        r"(?:구이|볶음|조림|무침|튀김|찜)(?!용|깨)|오징어젓|명란젓|낙지젓|고추참치|야채참치|페퍼콘|리얼바"
    ),
    "X05_복합소스": (
        r"소스|드레싱|초고추장|쌈장|굴소스|발사믹|쯔유|데리야끼|마요|케찹|케첩|"
        r"육수|다시다|연두순|연두진"
    ),
}


def load_reference(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    reference = root / "references" / "hansik"
    rules = pd.read_csv(reference / "ingredient_rules.csv", encoding="utf-8-sig").fillna("")
    sources = pd.DataFrame(json.loads((reference / "sources.json").read_text()))
    known = set(sources.source_id)
    assert rules.rule_id.is_unique and sources.source_id.is_unique
    assert all(set(ids.split(";")) <= known for ids in rules.source_ids)
    return rules, sources


def classify_products(
    products: pd.DataFrame, rules: pd.DataFrame, sources: pd.DataFrame
) -> pd.DataFrame:
    """포함은 사용 근거가 있는 재료 후보이며 실제 구매 후 한식 사용을 의미하지 않습니다."""
    compiled = [(row, re.compile(row.pattern)) for row in rules.itertuples()]
    exclusions = [(key, re.compile(value)) for key, value in FORM_EXCLUSIONS.items()]
    source_urls = sources.set_index("source_id").url.to_dict()
    records = []
    for product in products.itertuples(index=False):
        name = unicodedata.normalize("NFKC", product.sku_name)
        name = re.sub(r"\([^)]*판매종료[^)]*\)", "", name)
        name = re.sub(r"\s+", " ", name).strip()
        matches = []
        for row, pattern in compiled:
            found = list(pattern.finditer(name))
            if found:
                matches.append((row, found[-1]))
        all_matches = matches[:]
        # 상품 설명 앞부분에 나오는 부재료·브랜드명은 대표 재료로 사용하지 않습니다.
        if matches:
            matches = [max(matches, key=lambda pair: (pair[1].end(), len(pair[1].group())))]
        compact = name.replace(" ", "")
        blocked = next((key for key, pattern in exclusions if pattern.search(compact)), "")
        if (
            matches
            and matches[0][0].category in {"채소", "곡류", "과실·견과", "버섯", "기타 재료"}
            and re.search(r"\d\s*(?:ml|mL|ML|L|l)(?:\b|\s)", name)
        ):
            blocked = blocked or "X06_액상가공형태"
        ids = sorted({sid for row, _ in matches for sid in row.source_ids.split(";")})
        if blocked:
            status, reason = "excluded_form", "재료 중심 범위에서 제외되는 상품 형태"
        elif not matches:
            status, reason = "not_matched", "현재 근거 사전과 상품명 규칙으로 연결하지 못함"
        else:
            # 재료명에 뒤이어 다른 한글 명칭이 붙는 경우 혼합·가공품일 수 있습니다.
            safe_tail = re.compile(
                r"^(?:\s|[\d.,~×xX()/\[\]+%\-]|g|kg|ml|l|G|KG|ML|L|개|입|봉|팩|모|단|망|내외|이상|"
                r"국산|국내산|냉장|냉동|생물|자숙|건조|슬라이스|다짐육|다진|부침용|찌개용|국거리용|"
                r"구이용|불고기용|볶음용|이유식용|수육용|샤브샤브용|백숙용|조림용|김밥용|채|살|분말|"
                r"가루|대|중|소|특|용|장|구|cm|미|알|수|등급|암퇘지|선별|상|하|껍질|제거|지퍼|리필|"
                r"버섯|나물|컷|캔|속|통|팩|용기|봉지|인분|정육|세절|다리|가슴|안심|등심|목심|목살|"
                r"대패|통|덩어리|토막|절단|수육|보쌈용|사각|바른사각|골드|냉동보관)*$"
            )
            # 마지막 재료 뒤의 용량·단순 손질 표현만 자동 포함합니다.
            chosen = max(matches, key=lambda pair: pair[1].end())
            tail = name[chosen[1].end() :]
            ambiguous = bool(
                re.search(
                    r"메추리|스테비아|곤약|아임닭|용두동할매|촉촉오징어|아몬드|계란간장|미진|&|"
                    r"깐메추리|갈릭|블랙페퍼|옛날통닭|초생강|초밥식초|미소된장|맛간장|백간장|"
                    r"두부봉|계란연두부|땅콩가래떡|붉은대게|땡초된장|찌개용채소",
                    compact,
                )
            )
            categories = {row.category for row, _ in all_matches}
            if "육류" in categories and categories & {"채소", "양념"}:
                ambiguous = True
            if chosen[0].ingredient == "닭고기" and not re.search(
                r"생닭|생육|원육|냉장|냉동|무항생제|백숙용|볶음탕용|토종닭", name
            ):
                ambiguous = True
            if chosen[0].ingredient == "김" and not re.search(
                r"김밥|마른김|생김|무조미|100장", name
            ):
                ambiguous = True
            if chosen[0].category == "나물" and not re.search(
                r"생|건|냉동|데친|손질|깐|국산", name
            ):
                ambiguous = True
            if chosen[0].ingredient == "오징어" and not re.search(
                r"손질|냉동|생물|원양산|국내산|반건조|건오징어|마른오징어|진미채|솔방울", compact
            ):
                ambiguous = True
            if (
                chosen[0].ingredient == "무"
                and "무말랭이" in name
                and not re.search(r"건조|국내산|국산|말린", name)
            ):
                ambiguous = True
            if "두부" in name and chosen[0].category == "곡류":
                ambiguous = True
            if "닭" in name and chosen[0].ingredient == "돼지고기":
                ambiguous = True
            if "맛술" in name and chosen[0].ingredient == "생강":
                ambiguous = True
            if safe_tail.fullmatch(tail) and not ambiguous:
                status, reason = "included", "출처의 재료와 상품명 일치; 완제품 제외 규칙 통과"
            else:
                status, reason = (
                    "review",
                    f"혼합·조리 여부 또는 재료명 이후 상품 형태 확인 필요: {tail}",
                )
        records.append(
            {
                **product._asdict(),
                "classification": status,
                "classification_reason": reason,
                "exclusion_rule": blocked,
                "ingredient_names": ";".join(dict.fromkeys(row.ingredient for row, _ in matches)),
                "ingredient_categories": ";".join(
                    dict.fromkeys(row.category for row, _ in matches)
                ),
                "matched_terms": ";".join(dict.fromkeys(match.group() for _, match in matches)),
                "rule_ids": ";".join(row.rule_id for row, _ in matches),
                "source_ids": ";".join(ids),
                "source_urls": " | ".join(source_urls[sid] for sid in ids),
            }
        )
    return pd.DataFrame(records)
