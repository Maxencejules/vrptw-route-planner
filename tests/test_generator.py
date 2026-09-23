import math
import unittest

import support  # noqa: F401  (puts src/ on sys.path)

from vrptw import Instance, generate
from vrptw.generator import GeneratorSettings


def mean_gap_to_closest_customer(scenario):
    pts = [(c.x, c.y) for c in scenario.customers]
    gaps = []
    for i, (x, y) in enumerate(pts):
        gaps.append(min(math.hypot(x - a, y - b) for j, (a, b) in enumerate(pts) if j != i))
    return sum(gaps) / len(gaps)


class GeneratorTest(unittest.TestCase):
    def test_same_seed_gives_identical_scenario(self):
        for layout in ("uniform", "clustered"):
            with self.subTest(layout=layout):
                a = generate(customers=30, layout=layout, seed=7)
                b = generate(customers=30, layout=layout, seed=7)
                self.assertEqual(a, b)
                self.assertEqual(a.dumps(), b.dumps())

    def test_different_seeds_give_different_scenarios(self):
        for layout in ("uniform", "clustered"):
            with self.subTest(layout=layout):
                a = generate(customers=30, layout=layout, seed=1)
                b = generate(customers=30, layout=layout, seed=2)
                self.assertNotEqual(a.customers, b.customers)

    def test_size_ids_and_bounds(self):
        for layout in ("uniform", "clustered"):
            sc = generate(customers=45, layout=layout, seed=3, area=30.0)
            self.assertEqual(len(sc.customers), 45)
            self.assertEqual([c.id for c in sc.customers], list(range(1, 46)))
            for c in sc.customers:
                self.assertTrue(0 <= c.x <= 30 and 0 <= c.y <= 30)
                self.assertTrue(1 <= c.demand <= 10)
                self.assertTrue(5 <= c.service <= 15)
                self.assertLessEqual(c.ready, c.due)
            self.assertEqual(sc.generator["layout"], layout)
            self.assertEqual(sc.generator["seed"], 3)

    def test_every_customer_can_be_served_alone(self):
        for layout in ("uniform", "clustered"):
            for depot in ("center", "corner"):
                for seed in range(1, 6):
                    sc = generate(customers=40, layout=layout, depot=depot, seed=seed)
                    self.assertEqual(Instance(sc).unservable(), [], (layout, depot, seed))

    def test_clustered_layout_is_more_concentrated(self):
        for seed in range(1, 4):
            uniform = generate(customers=60, layout="uniform", seed=seed)
            clustered = generate(customers=60, layout="clustered", seed=seed)
            self.assertLess(
                mean_gap_to_closest_customer(clustered),
                mean_gap_to_closest_customer(uniform),
            )

    def test_fleet_size(self):
        sc = generate(customers=30, seed=4)
        needed = math.ceil(sc.total_demand / sc.fleet.capacity)
        self.assertGreaterEqual(sc.fleet.vehicles, needed)
        self.assertEqual(generate(customers=30, seed=4, vehicles=9).fleet.vehicles, 9)

    def test_settings_object_and_overrides(self):
        settings = GeneratorSettings(customers=12, layout="clustered", clusters=2, seed=5)
        self.assertEqual(generate(settings), generate(settings))
        self.assertEqual(len(generate(settings, customers=8).customers), 8)

    def test_invalid_settings(self):
        with self.assertRaises(ValueError):
            generate(layout="ring")
        with self.assertRaises(ValueError):
            generate(customers=0)
        with self.assertRaises(ValueError):
            generate(demand=(5, 80), capacity=60)
        with self.assertRaises(ValueError):
            generate(depot="middle")
        with self.assertRaisesRegex(ValueError, "cannot be served"):
            generate(shift_length=20)
        for name in ("area", "cluster_spread", "speed"):
            for value in (float("inf"), float("nan")):
                with self.subTest(name=name, value=value):
                    with self.assertRaisesRegex(ValueError, "finite"):
                        generate(layout="clustered", **{name: value})


if __name__ == "__main__":
    unittest.main()
