import math
import unittest
from dataclasses import replace
from unittest.mock import patch

import support
from support import make_scenario
from vrptw import Customer, Depot, Fleet, Instance, Scenario, ScenarioError, Solution, evaluate, generate, improve, solve
from vrptw.validation import audit_routes, exhaustive_tiny
from vrptw.report import format_report


class IndependentAuditTest(unittest.TestCase):
    def test_production_evaluator_rejects_non_integer_ids_in_direct_solutions(self):
        sc = make_scenario([(1, 0)])
        for cid in (True, 1.0, "1", [], {}):
            with self.subTest(cid=cid):
                ev = evaluate(sc, Solution(routes=[[cid]]))
                self.assertFalse(ev.feasible)
                self.assertEqual(ev.served, 0)
                self.assertTrue(any("unknown customer" in v for v in ev.violations))
                self.assertFalse(audit_routes(sc, [[cid]]).feasible)

    def test_objective_tolerance_cannot_disable_validation_with_nan_or_infinity(self):
        sc = make_scenario([(1, 0)])
        for invalid in (float("nan"), float("inf"), -1, True, "1", 10**400):
            with self.subTest(tolerance=invalid), self.assertRaises(ValueError):
                audit_routes(sc, [[1]], claimed_distance=0, distance_tolerance=invalid)
        self.assertFalse(audit_routes(sc, [[1]], claimed_distance=0, distance_tolerance=0).feasible)

    def test_raw_oracle_does_not_trust_production_helpers(self):
        sc = make_scenario([(3, 0), (3, 4), (0, 4)])
        with patch.object(Instance, "route_feasible", return_value=True), \
                patch.object(Instance, "total_distance", return_value=0), \
                patch("vrptw.solution.evaluate", side_effect=AssertionError("production oracle")):
            checked = audit_routes(sc, [[1, 3, 2]], claimed_distance=0)
            self.assertFalse(checked.feasible)
            self.assertEqual(checked.total_distance, 16)
            self.assertEqual(exhaustive_tiny(sc).distance, 14)

    def test_all_constraints_and_claimed_objective_are_checked(self):
        cases = [
            (make_scenario([(1, 0), (2, 0)]), [[1]], "not served"),
            (make_scenario([(1, 0)]), [[1, 1]], "more than once"),
            (make_scenario([(1, 0)]), [[True]], "unknown"),
            (make_scenario([(1, 0)]), [[99]], "unknown"),
            (make_scenario([(1, 0), (2, 0)]), [[1], [2]], "fleet"),
            (make_scenario([(1, 0), (2, 0)], capacity=1), [[1, 2]], "capacity"),
            (make_scenario([(2, 0)], windows=[(0, 1)]), [[1]], "due"),
            (make_scenario([(2, 0)], shift=3), [[1]], "shift"),
        ]
        for sc, routes, message in cases:
            with self.subTest(message=message, routes=routes):
                checked = audit_routes(sc, routes)
                self.assertFalse(checked.feasible)
                self.assertTrue(any(message in v for v in checked.violations))
        sc = make_scenario([(1, 0)])
        for wrong in (0, float("nan"), float("inf"), True, "2", 10**400):
            with self.subTest(claimed=wrong):
                self.assertFalse(audit_routes(sc, [[1]], claimed_distance=wrong).feasible)
        self.assertTrue(audit_routes(sc, [[], [1], []], claimed_distance=2).feasible)

    def test_service_start_and_return_boundaries_waiting_and_speed(self):
        sc = make_scenario([(3, 4)], speed=30, windows=[(20, 20)], services=[5], shift=35)
        checked = audit_routes(sc, [[1]])  # travel10, wait10, service5, return10
        self.assertTrue(checked.feasible)
        self.assertEqual(checked.total_distance, 10)
        shorter = replace(sc, fleet=replace(sc.fleet, shift_length=35 - 2e-6))
        self.assertFalse(audit_routes(shorter, [[1]]).feasible)

    def test_all_variants_cross_checked_on_seeded_layouts(self):
        for layout in ("uniform", "clustered"):
            for seed in (1, 7, 19):
                sc = generate(customers=20, layout=layout, seed=seed)
                for solver, metric in (("nearest", "time"), ("nearest", "distance"), ("savings", "time")):
                    before = solve(sc, solver, nn_metric=metric)
                    before_cost = audit_routes(sc, before.routes).total_distance
                    for improved in (False, True):
                        with self.subTest(layout=layout, seed=seed, solver=solver, metric=metric, improved=improved):
                            sol = solve(sc, solver, nn_metric=metric, improve=improved)
                            ev = evaluate(sc, sol)
                            checked = audit_routes(sc, sol.routes, claimed_distance=ev.total_distance)
                            self.assertTrue(checked.feasible, checked.violations)
                            self.assertEqual(checked.feasible, ev.feasible)
                            self.assertEqual(checked.vehicles_used, ev.vehicles_used)
                            self.assertLessEqual(checked.total_distance, before_cost + 1e-9)


class ExhaustiveReferenceTest(unittest.TestCase):
    def test_enumeration_count_and_hand_computed_optima(self):
        cases = [
            (make_scenario([(3, 0), (3, 4), (0, 4)]), 14),
            (make_scenario([(10, 0), (11, 0), (-10, 0), (-11, 0)], capacity=6,
                           demands=[3]*4, vehicles=2), 44),
            (make_scenario([(1, 0), (2, 0)], windows=[(100, 200), (0, 50)], vehicles=2), 4),
            (make_scenario([(10, 0), (0, 10)], shift=30, vehicles=2), 40),
        ]
        for sc, expected in cases:
            result = exhaustive_tiny(sc)
            self.assertEqual(result.distance, expected)
            n = len(sc.customers)
            self.assertEqual(result.plans_considered, math.factorial(n)*2**(n-1))
            self.assertTrue(audit_routes(sc, result.routes, claimed_distance=expected).feasible)

    def test_no_feasible_plan_empty_and_size_guard(self):
        sc = make_scenario([(10, 0), (0, 10)], shift=30, vehicles=1)
        self.assertIsNone(exhaustive_tiny(sc).distance)
        empty = make_scenario([])
        self.assertEqual(exhaustive_tiny(empty).distance, 0)
        self.assertEqual(exhaustive_tiny(empty).plans_considered, 1)
        with self.assertRaises(ValueError):
            exhaustive_tiny(make_scenario([(i, 0) for i in range(7)]))


class NumericAndBudgetRegressionTest(unittest.TestCase):
    def test_direct_dataclasses_reject_invalid_numbers_and_integer_fields(self):
        base = make_scenario([(1, 0)])
        for owner, fields in ((base.depot, ("x", "y")),
                              (base.fleet, ("capacity", "speed", "shift_length")),
                              (base.customers[0], ("x", "y", "demand", "ready", "due", "service"))):
            for field in fields:
                for value in (float("nan"), float("inf"), True, "1", 10**400):
                    with self.subTest(type=type(owner).__name__, field=field, value=value):
                        part = replace(owner, **{field: value})
                        with self.assertRaises(ScenarioError):
                            Scenario("bad", part if isinstance(part, Depot) else base.depot,
                                     part if isinstance(part, Fleet) else base.fleet,
                                     [part] if isinstance(part, Customer) else base.customers)
        for value in (True, 1.5, "1"):
            with self.assertRaises(ScenarioError):
                replace(base, fleet=replace(base.fleet, vehicles=value))
            with self.assertRaises(ScenarioError):
                replace(base, customers=[replace(base.customers[0], id=value)])

    def test_derived_geometry_overflow_is_rejected(self):
        for sc in (make_scenario([(1e308, 0)], depot=(-1e308, 0)),
                   make_scenario([(1, 0)], speed=5e-324)):
            with self.assertRaises(ScenarioError):
                Instance(sc)

    def test_zero_move_budget_performs_no_move_and_rejects_bad_budgets(self):
        inst = Instance(make_scenario([(3, 0), (3, 4), (0, 4)]))
        start = [[1, 3, 2]]
        routes, stats = improve(inst, start, max_moves=0)
        self.assertEqual(routes, start)
        self.assertIsNot(routes[0], start[0])
        self.assertEqual(stats.total_moves, 0)
        self.assertEqual(stats.start_distance, stats.end_distance)
        self.assertTrue(stats.stopped_early)
        for value in (-1, True, 0.5, "1"):
            with self.assertRaises(ValueError):
                improve(inst, start, max_moves=value)
        sol = solve(inst.scenario, improve=True, max_moves=0)
        self.assertEqual(sol.search["moves"], {"2-opt": 0, "relocate": 0, "exchange": 0})
        self.assertEqual(sol.options["max_moves"], 0)
        report = format_report(inst.scenario, sol, evaluate(inst.scenario, sol), show_timeline=False)
        self.assertIn("nearest (nn_metric=time) + local search", report)
        self.assertIn("accepted-move budget exhausted (0)", report)


if __name__ == "__main__":
    unittest.main()
