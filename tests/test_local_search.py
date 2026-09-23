import math
import unittest

import support  # noqa: F401
from support import brute_force_optimum, make_scenario

from vrptw import Instance, generate, improve
from vrptw.nearest import nearest_neighbour
from vrptw.savings import clarke_wright


class LocalSearchTest(unittest.TestCase):
    def test_never_increases_distance_and_keeps_feasibility(self):
        for layout in ("uniform", "clustered"):
            for seed in range(1, 9):
                inst = Instance(generate(customers=35, layout=layout, seed=seed))
                starts = {
                    "nearest-time": nearest_neighbour(inst, "time")[0],
                    "nearest-distance": nearest_neighbour(inst, "distance")[0],
                    "savings": clarke_wright(inst),
                }
                for label, routes in starts.items():
                    with self.subTest(layout=layout, seed=seed, start=label):
                        before = inst.total_distance(routes)
                        after_routes, stats = improve(inst, routes)
                        after = inst.total_distance(after_routes)
                        self.assertLessEqual(after, before + 1e-9)
                        self.assertAlmostEqual(stats.start_distance, before)
                        self.assertAlmostEqual(stats.end_distance, after)
                        self.assertTrue(all(inst.route_feasible(r) for r in after_routes))
                        self.assertLessEqual(len(after_routes), len(routes))
                        self.assertEqual(
                            sorted(n for r in after_routes for n in r),
                            sorted(n for r in routes for n in r),
                        )

    def test_improves_one_route_per_customer(self):
        inst = Instance(generate(customers=20, layout="clustered", seed=3))
        singles = [[n] for n in range(1, inst.size)]
        routes, stats = improve(inst, singles)
        self.assertLess(inst.total_distance(routes), inst.total_distance(singles))
        self.assertLess(len(routes), len(singles))
        self.assertGreater(stats.moves["relocate"], 0)

    def test_input_routes_are_not_modified(self):
        inst = Instance(generate(customers=15, seed=2))
        singles = [[n] for n in range(1, inst.size)]
        snapshot = [list(r) for r in singles]
        improve(inst, singles)
        self.assertEqual(singles, snapshot)

    def test_two_opt_removes_a_crossing(self):
        inst = Instance(make_scenario([(3, 0), (3, 4), (0, 4)]))
        routes, stats = improve(inst, [[1, 3, 2]])  # 3 + 5 + 3 + 5 = 16
        self.assertEqual(routes, [[1, 2, 3]])
        self.assertAlmostEqual(inst.total_distance(routes), 14.0)
        self.assertEqual(stats.moves, {"2-opt": 1, "relocate": 0, "exchange": 0})

    def test_relocate_empties_a_route(self):
        sc = make_scenario([(1, 0), (2, 0)], windows=[(100, 200), (0, 50)], vehicles=2)
        inst = Instance(sc)
        routes, stats = improve(inst, [[1], [2]])
        self.assertEqual(routes, [[2, 1]])
        self.assertAlmostEqual(inst.total_distance(routes), brute_force_optimum(sc))
        self.assertEqual(stats.moves["relocate"], 1)

    def test_exchange_when_capacity_blocks_relocation(self):
        sc = make_scenario(
            [(-10, 0), (-10, 1), (10, 0), (10, 1)], capacity=2, vehicles=2
        )
        inst = Instance(sc)
        routes, stats = improve(inst, [[1, 4], [3, 2]])
        self.assertEqual(stats.moves["relocate"], 0)
        self.assertGreaterEqual(stats.moves["exchange"], 1)
        expected = 2 * (10 + 1 + math.sqrt(101))
        self.assertAlmostEqual(inst.total_distance(routes), expected)
        self.assertAlmostEqual(brute_force_optimum(sc), expected)

    def test_end_of_shift_blocks_a_shorter_joined_route(self):
        # Joining the two customers would save 20 - sqrt(200) km, but the
        # vehicle would come back at 34.1, after the 30-minute shift. Every
        # due time equals the shift length and would still be met.
        points = [(10, 0), (0, 10)]
        inst = Instance(make_scenario(points, shift=30, vehicles=2))
        routes, stats = improve(inst, [[1], [2]])
        self.assertEqual(routes, [[1], [2]])
        self.assertEqual(stats.total_moves, 0)
        # With a 35-minute shift the same relocation is accepted.
        inst = Instance(make_scenario(points, shift=35, vehicles=2))
        routes, stats = improve(inst, [[1], [2]])
        self.assertEqual(len(routes), 1)
        self.assertEqual(stats.moves["relocate"], 1)
        self.assertAlmostEqual(inst.total_distance(routes), 20 + math.sqrt(200))

    def test_rejects_infeasible_start(self):
        inst = Instance(make_scenario([(1, 0), (2, 0)], demands=[5, 5], capacity=6, vehicles=2))
        with self.assertRaises(ValueError):
            improve(inst, [[1, 2]])

    def test_move_limit(self):
        inst = Instance(generate(customers=20, seed=5))
        singles = [[n] for n in range(1, inst.size)]
        routes, stats = improve(inst, singles, max_moves=1)
        self.assertTrue(stats.stopped_early)
        self.assertEqual(stats.total_moves, 1)
        self.assertEqual(len(routes), len(singles) - 1)


if __name__ == "__main__":
    unittest.main()
