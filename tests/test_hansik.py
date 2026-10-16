import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from hit_stocks_analysis.hansik import classify_products, load_reference
from hit_stocks_analysis.hansik_dataset import build_dataset

ROOT = Path(__file__).resolve().parents[1]


class HansikTests(unittest.TestCase):
    def test_ingredient_and_finished_product_collisions(self):
        included = {
            "국내산 애호박 1개": "애호박",
            "양지뜨레 무항생제 대란 30구": "달걀",
            "킬로미트 우삼겹 1kg": "소고기",
            "풀무원 SOGA 부드러운찌개두부 300g": "두부",
            "무항생제 한돈 냉장 삼겹살 구이용 600g": "돼지고기",
            "오늘의곡물 국산 찰보리쌀 800g": "보리",
            "국내산 깐마늘 100g": "마늘",
        }
        rejected = [
            "마늘 소시지 200g",
            "농심 자갈치 90g",
            "아이보리 비누 100g",
            "고추장 삼겹살 500g",
            "냉장 닭가슴살 갈릭 100g",
            "아이스 군 고구마 120g",
            "동원 고추참치 90g",
            "차오차이 마파두부 180g",
            "오리온 눈을감자 96g",
            "풀무원 두부봉 180g",
            "밀빛 새우 완당면 642g",
            "국내산 귀리쌀 500g",
        ]
        frame = pd.DataFrame({"sku_name": list(included) + rejected})
        result = classify_products(frame, *load_reference(ROOT)).set_index("sku_name")
        for name, ingredient in included.items():
            with self.subTest(name=name):
                self.assertEqual(result.loc[name, "classification"], "included")
                self.assertEqual(result.loc[name, "ingredient_names"], ingredient)
                self.assertTrue(result.loc[name, "source_urls"])
        for name in rejected:
            with self.subTest(name=name):
                self.assertNotEqual(result.loc[name, "classification"], "included")

    def test_build_filters_rows_and_counts_orders_without_join_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "references", root / "references")
            rows = [
                ("1", "A", "2025-01-01 09:00", "S1", "깐마늘 100g", 2, "SHIPPED"),
                ("2", "A", "2025-01-01 09:10", "S1", "깐마늘 100g", 3, "SHIPPED"),
                ("3", "A", "2025-01-01 10:00", "S1", "깐마늘 100g", 1, "SHIPPED"),
                ("4", "B", "2025-01-01 09:00", "S2", "마늘 소시지 200g", 1, "SHIPPED"),
                ("5", "C", "2025-01-01 09:00", "S3", "두부 300g", 0, "SHIPPED"),
                ("6", "D", "2025-01-01 09:00", "S1", "깐마늘 100g", 4, "CANCELLED"),
                ("7", "E", "2024-12-31 09:00", "S1", "깐마늘 100g", 4, "SHIPPED"),
            ]
            pd.DataFrame(
                rows,
                columns=[
                    "splitOrderId",
                    "orderId(주문번호)",
                    "outboundRequestDateTime",
                    "skuCode",
                    "skuName",
                    "pickingQuantity",
                    "status",
                ],
            ).to_csv(root / "outbound_2025-fixture.csv", index=False)
            stats = build_dataset(root)
            self.assertEqual(stats["catalog_skus"], 3)
            self.assertEqual(stats["selected_skus"], 2)
            self.assertEqual(stats["selected_outbound_rows"], 3)
            self.assertEqual(stats["selected_unique_orders"], 1)
            self.assertEqual(stats["selected_picked_quantity"], 6)
            hourly = pd.read_csv(root / "reports/hansik_2025/hourly_all_products.csv")
            self.assertEqual(hourly.order_count.tolist(), [1, 1])
            self.assertEqual(hourly.picked_quantity.tolist(), [5, 1])
            self.assertEqual(hourly["rank"].tolist(), [1, 1])
            products = pd.read_csv(root / "data/hansik_2025/products.csv")
            self.assertEqual(products.set_index("sku_code").loc["S1", "annual_order_count"], 1)
            actual = pd.read_parquet(root / "data/hansik_2025/outbound_ingredients.parquet")
            self.assertEqual(actual.splitOrderId.tolist(), ["1", "2", "3"])


if __name__ == "__main__":
    unittest.main()
