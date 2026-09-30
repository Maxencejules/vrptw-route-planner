import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import support
from vrptw.benchmark import load_solomon
from vrptw.model import ScenarioError
from vrptw.validation import audit_routes
from vrptw.planner import solve

ROOT = Path(support.ROOT)
FIXTURE = ROOT / "benchmarks" / "c101.txt"


class SolomonBenchmarkTest(unittest.TestCase):
    def test_all_six_c101_variants_are_deterministic_and_independently_feasible(self):
        sc = load_solomon(FIXTURE)
        for solver, metric in (("nearest", "time"), ("nearest", "distance"), ("savings", "time")):
            for improved in (False, True):
                with self.subTest(solver=solver, metric=metric, improved=improved):
                    a = solve(sc, solver, nn_metric=metric, improve=improved, max_moves=1000)
                    b = solve(sc, solver, nn_metric=metric, improve=improved, max_moves=1000)
                    self.assertEqual(a.routes, b.routes)
                    checked = audit_routes(sc, a.routes)
                    self.assertTrue(checked.feasible, checked.violations)
                    self.assertEqual(checked.total_distance, audit_routes(sc, b.routes).total_distance)

    def test_official_fixture_hash_and_full_customer_selection(self):
        reference = json.loads(FIXTURE.with_suffix(".reference.json").read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), reference["instance_sha256"])
        sc = load_solomon(FIXTURE)
        self.assertEqual(sc.name, "C101")
        self.assertEqual([c.id for c in sc.customers], list(range(1, 101)))
        self.assertEqual(sc.fleet.vehicles, 25)
        self.assertEqual(sc.fleet.capacity, 200)
        self.assertEqual(sc.fleet.speed, 60)
        self.assertEqual(sc.fleet.shift_length, 1236)
        self.assertEqual((sc.depot.x, sc.depot.y), (40, 50))
        self.assertEqual(sc.customer(1).service, 90)

    def test_published_routes_are_feasible_and_match_distance_convention(self):
        reference = json.loads(FIXTURE.with_suffix(".reference.json").read_text(encoding="utf-8"))
        checked = audit_routes(load_solomon(FIXTURE), reference["routes"])
        self.assertTrue(checked.feasible, checked.violations)
        self.assertEqual(checked.vehicles_used, 10)
        self.assertEqual(round(checked.total_distance, 2), 828.94)

    def test_importer_refuses_unsupported_depot_and_malformed_rows(self):
        template = "TINY\nVEHICLE\nNUMBER CAPACITY\n2 10\nCUSTOMER\nCUST NO. X Y DEMAND READY DUE SERVICE\n{depot}\n{customer}\n"
        cases = [("0 0 0 0 1 100 0", "1 1 0 1 0 99 0"),
                 ("0 0 0 0 0 100 1", "1 1 0 1 0 99 0"),
                 ("0 0 0 1 0 100 0", "1 1 0 1 0 99 0"),
                 ("1 0 0 0 0 100 0", "2 1 0 1 0 99 0"),
                 ("0 0 0 0 0 100 0", "1 1 0 1 0 99"),
                 ("0 0 0 0 0 100 0", "1 1 0 1 0 99 0\n1 2 0 1 0 99 0"),
                 ("0 0 0 0 0 100 0", "1 nan 0 1 0 99 0")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.txt"
            for depot, customer in cases:
                path.write_text(template.format(depot=depot, customer=customer), encoding="ascii")
                with self.subTest(depot=depot, customer=customer), self.assertRaises(ScenarioError):
                    load_solomon(path)


if __name__ == "__main__":
    unittest.main()
