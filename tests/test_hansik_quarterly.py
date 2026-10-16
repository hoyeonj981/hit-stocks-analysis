import shutil
import tempfile
import unittest
from pathlib import Path

import duckdb
import pandas as pd

from hit_stocks_analysis.hansik_dataset import build_dataset
from hit_stocks_analysis.hansik_quarterly import aggregate_quarterly


class QuarterlyTests(unittest.TestCase):
    def test_calendar_boundary_distinct_orders_and_tie_break(self):
        records = pd.DataFrame(
            [
                ("2026-03-31 23:00", "A", "S1", 1),
                ("2026-03-31 23:01", "A", "S1", 2),
                ("2026-04-01 00:00", "A", "S1", 1),
                ("2026-04-01 01:00", "A", "S1", 1),
                ("2026-04-02 00:00", "B", "S2", 3),
                ("2026-07-01 12:00", "C", "S1", 1),
            ],
            columns=["requested_at", "order_id", "sku_code", "picked_quantity"],
        )
        records.requested_at = pd.to_datetime(records.requested_at)
        records["hour"] = records.requested_at.dt.hour
        with duckdb.connect() as con:
            con.register("outbound", records)
            ranked, hourly = aggregate_quarterly(con)
        self.assertEqual(ranked.quarter.unique().tolist(), [1, 2, 3])
        q1 = ranked[ranked.quarter == 1].iloc[0]
        self.assertEqual((q1.quarter_order_count, q1.quarter_picked_quantity), (1, 3))
        self.assertEqual(ranked[ranked.quarter == 2].sku_code.tolist(), ["S2", "S1"])
        q2_s1 = hourly[(hourly.quarter == 2) & (hourly.sku_code == "S1")]
        self.assertEqual(q2_s1.order_count.tolist(), [1, 1])
        self.assertEqual(ranked.quarter_order_count.sum(), 4)
        self.assertEqual(hourly.picked_quantity.sum(), 9)

    def test_dataset_year_parameter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(Path(__file__).resolve().parents[1] / "references", root / "references")
            pd.DataFrame(
                [
                    ("1", "A", "2026-01-01 12:00", "S1", "깐마늘 100g", 1, "SHIPPED"),
                    ("2", "B", "2025-12-31 12:00", "S1", "깐마늘 100g", 2, "SHIPPED"),
                ],
                columns=[
                    "splitOrderId",
                    "orderId(주문번호)",
                    "outboundRequestDateTime",
                    "skuCode",
                    "skuName",
                    "pickingQuantity",
                    "status",
                ],
            ).to_csv(root / "outbound_2026-fixture.csv", index=False)
            result = build_dataset(root, year=2026)
            self.assertEqual(result["selected_outbound_rows"], 1)
            self.assertEqual(result["selected_picked_quantity"], 1)
            self.assertTrue((root / "reports/hansik_2026/hansik_ingredients_2026.xlsx").exists())
            self.assertFalse((root / "data/hansik_2025").exists())


if __name__ == "__main__":
    unittest.main()
