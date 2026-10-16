"""주문 분할, 기간 경계, 출고 제외 조건이 순위에 미치는 영향을 검증합니다."""

import unittest

import duckdb

from scripts.analyze_hourly_2025 import aggregate


class HourlyAnalysisTest(unittest.TestCase):
    def test_order_frequency_and_filtering(self):
        rows = [
            ("2025-01-01 09:00:00", "001", "01", "A", "SHIPPED", "2"),
            ("2025-01-01 09:01:00", "001", "01", "A", "SHIPPED", "3"),
            ("2025-01-02 09:00:00", "002", "01", "A", "SHIPPED", "1"),
            ("2025-01-01 09:00:00", "001", "02", "B", "SHIPPED", "100"),
            ("2025-12-31 23:59:59", "003", "01", "A", "SHIPPED", "1"),
            ("2025-01-01 09:00:00", "004", "03", "Zero", "SHIPPED", "0"),
            ("2025-01-01 09:00:00", "005", "03", "Cancel", "CANCELLED", "10"),
            ("2026-01-01 00:00:00", "006", "03", "Next year", "SHIPPED", "10"),
            ("2024-12-31 23:59:59", "007", "03", "Previous year", "SHIPPED", "10"),
            ("bad-date", "008", "03", "Bad date", "SHIPPED", "10"),
            ("2025-01-01 09:00:00", "009", "03", "Bad qty", "SHIPPED", "x"),
            ("2025-01-01 09:00:00", "", "03", "No ID", "SHIPPED", "10"),
        ]
        with duckdb.connect() as connection:
            connection.execute("""CREATE TABLE raw (
                outboundRequestDateTime VARCHAR, "orderId(주문번호)" VARCHAR,
                skuCode VARCHAR, skuName VARCHAR, status VARCHAR, pickingQuantity VARCHAR
            )""")
            connection.executemany("INSERT INTO raw VALUES (?, ?, ?, ?, ?, ?)", rows)
            ranked, hourly = aggregate(connection)
        nine = ranked[ranked.hour == 9].reset_index(drop=True)
        self.assertEqual(nine.sku_code.tolist(), ["01", "02"])
        self.assertEqual(nine.order_count.tolist(), [2, 1])
        self.assertEqual(nine.picked_quantity.tolist(), [6, 100])
        self.assertEqual(nine.order_share_pct.tolist(), [100, 50])
        self.assertEqual(hourly.loc[hourly.hour == 9, "total_orders"].item(), 2)
        self.assertEqual(hourly.loc[hourly.hour == 0, "total_orders"].item(), 0)
        self.assertEqual(ranked.loc[ranked.hour == 23, "order_count"].item(), 1)
        self.assertEqual(hourly.picked_quantity.sum(), 107)
        self.assertEqual(len(hourly), 24)


if __name__ == "__main__":
    unittest.main()
