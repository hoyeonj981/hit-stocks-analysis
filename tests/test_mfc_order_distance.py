"""중복 방문·공통 통과 구간·위치 누락이 비용과 통계를 왜곡하지 않는지 검증."""

import unittest

import pandas as pd

from hit_stocks_analysis.mfc_order_distance import calculate_order_costs


def picks(codes):
    return pd.DataFrame({"order_id": "one", "rack_code": codes,
                         "requested_at": pd.Timestamp("2026-09-01"), "split_order_id": "s1"})


class OrderDistanceTest(unittest.TestCase):
    def setUp(self):
        self.features = pd.DataFrame([
            ("C01-01", "ambient", 12, "C:1:up", 1),
            ("C01-03", "ambient", 5, "C:1:up", 0.5),
            ("B01-01", "cold", 8, "B:1:down", 5),
            ("D01-01", "ambient", 20, "D:1:down", 4),
            ("A01-01", "cold", 25, "A:1:down", 3),
        ], columns=["rack_code", "direction", "depth", "branch", "lateral"]
        ).set_index("rack_code")

    def cost(self, codes, tau=0, features=None):
        orders, _ = calculate_order_costs(
            picks(codes), self.features if features is None else features, tau=tau)
        return orders.loc["one"]

    def test_hand_calculated_example_and_threshold(self):
        self.assertEqual(self.cost(["C01-01", "B01-01"]).distance_cost, 52)
        self.assertEqual(self.cost(["C01-01", "B01-01"], tau=2).distance_cost, 46)

    def test_same_rack_or_nearer_rack_adds_no_distance(self):
        base = self.cost(["C01-01"]).distance_cost
        self.assertEqual(self.cost(["C01-01"] * 3).distance_cost, base)
        self.assertEqual(self.cost(["C01-01", "C01-03"]).distance_cost, base)

    def test_c_d_and_a_b_use_max_depth_not_sum(self):
        row = self.cost(["C01-01", "D01-01", "B01-01", "A01-01"])
        self.assertEqual(row.ambient_depth, 20)
        self.assertEqual(row.cold_depth, 25)
        self.assertEqual(row.depth_cost, 90)

    def test_opposite_sides_are_both_counted(self):
        features = self.features.copy()
        features.loc["C01-03", ["branch", "lateral"]] = ["C:1:down", 4]
        row = self.cost(["C01-01", "C01-03"], features=features)
        self.assertEqual(row.lateral_cost, 10)

    def test_unknown_rack_excludes_order_without_erasing_partial_cost(self):
        row = self.cost(["C01-01", "M01-01"])
        self.assertFalse(row.complete)
        self.assertTrue(pd.isna(row.distance_cost))
        self.assertTrue(pd.isna(row.cost_rank))
        self.assertEqual(row.known_rack_cost, 26)
        self.assertEqual(row.unmapped_rows, 1)

    def test_all_unknown_orders_are_not_zero_distance_orders(self):
        row = self.cost(["M01-01"])
        self.assertTrue(pd.isna(row.distance_cost))
        self.assertFalse(row.complete)

    def test_a_visit_adds_b_exit_but_shared_exit_is_not_counted_twice(self):
        features = self.features.copy()
        features.loc["B_TO_A"] = ["cold", 17, "B:1:down", 6]
        a_only = self.cost(["A01-01"], features=features)
        combined = self.cost(["A01-01", "B01-01"], features=features)
        self.assertEqual(a_only.distance_cost, 2 * 25 + 2 * (3 + 6))
        self.assertEqual(combined.distance_cost, a_only.distance_cost)

    def test_more_distant_racks_cannot_reduce_cost(self):
        base = self.cost(["C01-01", "B01-01"]).distance_cost
        self.assertGreaterEqual(self.cost(list(self.features.index)).distance_cost, base)


if __name__ == "__main__":
    unittest.main()
