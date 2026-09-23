import math
import unittest
from dataclasses import replace

import support  # noqa: F401
from support import brute_force_optimum, make_scenario

from vrptw import Instance, InfeasibleScenarioError, Scenario, Solution, evaluate, generate, solve

VARIANTS = (
    ("nearest", "time"),
    ("nearest", "distance"),
    ("savings", "time"),  # the metric is ignored by the savings solver
)


def square_scenario():
    # Corners of a 3 x 4 rectangle with the depot at the fourth corner.
    return make_scenario([(3, 0), (3, 4), (0, 4)])


def two_wing_scenario():
    # Capacity 6 and demand 3 each: two customers per vehicle.
    return make_scenario(
        [(10, 0), (11, 0), (-10, 0), (-11, 0)], demands=[3, 3, 3, 3], capacity=6, vehicles=2
    )


def window_order_scenario():
    # Customer 1 is closer but opens late; customer 2 closes early.
    return make_scenario([(1, 0), (2, 0)], windows=[(100, 200), (0, 50)], vehicles=2)


def shift_split_scenario(vehicles=2):
    # Windows stay open until the end of the 30-minute shift. Each customer
    # alone takes 20 minutes; both on one route take 20 + sqrt(200) = 34.1
    # minutes. Customer 2 is then reached at 24.1, before its due time, so
    # only the return by the end of the shift rules that route out. Joining
    # them would save 20 - sqrt(200) km, so the solvers would like to.
    return make_scenario([(10, 0), (0, 10)], shift=30, vehicles=vehicles)


def open_window_scenario(layout, seed, shift):
    # A generated layout with every window open for the whole shift and one
    # vehicle per customer, so the end of the shift is the only time limit.
    base = generate(customers=15, layout=layout, seed=seed)
    return Scenario(
        name=f"open-{layout}-{seed}",
        depot=base.depot,
        fleet=replace(base.fleet, vehicles=len(base.customers), shift_length=shift),
        customers=[replace(c, ready=0, due=shift) for c in base.customers],
    )


class GeneratedScenarioTest(unittest.TestCase):
    def test_every_solver_output_is_feasible(self):
        for layout in ("uniform", "clustered"):
            for size in (12, 30):
                for seed in range(1, 7):
                    sc = generate(customers=size, layout=layout, seed=seed)
                    for solver, metric in VARIANTS:
                        for improve in (False, True):
                            with self.subTest(layout=layout, size=size, seed=seed,
                                              solver=solver, metric=metric, improve=improve):
                                sol = solve(sc, solver, improve=improve, nn_metric=metric)
                                ev = evaluate(sc, sol)
                                self.assertTrue(ev.feasible, ev.violations)
                                self.assertEqual(ev.served, size)
                                self.assertEqual(sol.unassigned, [])
                                visited = sorted(c for r in sol.routes for c in r)
                                self.assertEqual(visited, list(range(1, size + 1)))

    def test_solvers_are_deterministic(self):
        sc = generate(customers=25, layout="clustered", seed=9)
        for solver, metric in VARIANTS:
            a = solve(sc, solver, improve=True, nn_metric=metric)
            b = solve(sc, solver, improve=True, nn_metric=metric)
            self.assertEqual(a.routes, b.routes)

    def test_never_better_than_exact_optimum_on_tiny_instances(self):
        for layout in ("uniform", "clustered"):
            for seed in range(1, 4):
                sc = generate(customers=6, layout=layout, seed=seed, vehicles=3)
                best = brute_force_optimum(sc)
                self.assertIsNotNone(best)
                for solver, metric in VARIANTS:
                    ev = evaluate(sc, solve(sc, solver, improve=True, nn_metric=metric))
                    self.assertTrue(ev.feasible)
                    self.assertGreaterEqual(ev.total_distance, best - 1e-9)


class HandCheckedTest(unittest.TestCase):
    def test_square_known_optimum(self):
        sc = square_scenario()
        self.assertAlmostEqual(brute_force_optimum(sc), 14.0)
        for solver, metric in VARIANTS:
            for improve in (False, True):
                ev = evaluate(sc, solve(sc, solver, improve=improve, nn_metric=metric))
                self.assertTrue(ev.feasible)
                self.assertAlmostEqual(ev.total_distance, 14.0)

    def test_capacity_forces_two_routes(self):
        sc = two_wing_scenario()
        self.assertAlmostEqual(brute_force_optimum(sc), 44.0)
        for solver, metric in VARIANTS:
            sol = solve(sc, solver, improve=True, nn_metric=metric)
            ev = evaluate(sc, sol)
            self.assertTrue(ev.feasible)
            self.assertAlmostEqual(ev.total_distance, 44.0)
            self.assertEqual(sorted(sorted(r) for r in sol.routes), [[1, 2], [3, 4]])

    def test_time_windows_decide_the_order(self):
        sc = window_order_scenario()
        self.assertAlmostEqual(brute_force_optimum(sc), 4.0)
        # Time-based nearest neighbour serves the early-closing customer first.
        sol = solve(sc, "nearest", nn_metric="time")
        self.assertEqual(sol.routes, [[2, 1]])
        self.assertAlmostEqual(evaluate(sc, sol).total_distance, 4.0)
        # Distance-based nearest neighbour goes to customer 1 first, which
        # leaves customer 2 for a second vehicle (distance 6).
        sol = solve(sc, "nearest", nn_metric="distance")
        self.assertEqual(sol.routes, [[1], [2]])
        self.assertAlmostEqual(evaluate(sc, sol).total_distance, 6.0)
        self.assertEqual(solve(sc, "savings").routes, [[2, 1]])

    def test_small_fleet_leaves_customers_unassigned(self):
        sc = make_scenario([(1, 0), (0, 1), (-1, 0)], capacity=2, vehicles=1)
        sol = solve(sc, "nearest")
        self.assertEqual(len(sol.unassigned), 1)
        ev = evaluate(sc, sol)
        self.assertFalse(ev.feasible)
        self.assertTrue(any("not served" in v for v in ev.violations))

    def test_savings_reports_fleet_shortage(self):
        # Every customer needs a vehicle of its own, but only two exist.
        sc = make_scenario([(5, 0), (0, 5), (-5, 0)], demands=[2, 2, 2], capacity=2, vehicles=2)
        ev = evaluate(sc, solve(sc, "savings"))
        self.assertFalse(ev.feasible)
        self.assertEqual(ev.vehicles_used, 3)
        self.assertTrue(any("vehicles available" in v for v in ev.violations))


class ShiftLimitTest(unittest.TestCase):
    """Plans in which the end of the shift, not a time window, is the limit."""

    def test_shift_rules_out_the_joined_route(self):
        sc = shift_split_scenario()
        inst = Instance(sc)
        for joined in ([1, 2], [2, 1]):
            back = inst.return_time(joined)
            self.assertIsNotNone(back)  # every due time is met
            self.assertAlmostEqual(back, 20 + math.sqrt(200))
            self.assertFalse(inst.route_feasible(joined))
        self.assertTrue(inst.route_feasible([1]))
        self.assertTrue(inst.route_feasible([2]))
        ev = evaluate(sc, Solution(routes=[[1, 2]]))
        self.assertEqual(
            ev.violations, ("vehicle 1: back at depot at 34.1, after the end of the shift 30",)
        )

    def test_every_solver_splits_at_the_end_of_the_shift(self):
        sc = shift_split_scenario()
        self.assertAlmostEqual(brute_force_optimum(sc), 40.0)
        for solver, metric in VARIANTS:
            for improve in (False, True):
                with self.subTest(solver=solver, metric=metric, improve=improve):
                    sol = solve(sc, solver, improve=improve, nn_metric=metric)
                    ev = evaluate(sc, sol)
                    self.assertTrue(ev.feasible, ev.violations)
                    self.assertEqual(sorted(sol.routes), [[1], [2]])
                    self.assertAlmostEqual(ev.total_distance, 40.0)

    def test_left_over_insertion_respects_the_shift(self):
        # With one vehicle, nearest neighbour serves customer 1, and customer
        # 2 cannot be inserted before or after it without a late return.
        sol = solve(shift_split_scenario(vehicles=1), "nearest")
        self.assertEqual(sol.routes, [[1]])
        self.assertEqual(sol.unassigned, [2])

    def test_generated_layouts_with_a_binding_shift(self):
        for layout in ("uniform", "clustered"):
            for seed in range(1, 5):
                tight = open_window_scenario(layout, seed, shift=150)
                loose = open_window_scenario(layout, seed, shift=100_000)
                for solver, metric in VARIANTS:
                    for improve in (False, True):
                        with self.subTest(layout=layout, seed=seed, solver=solver,
                                          metric=metric, improve=improve):
                            sol = solve(tight, solver, improve=improve, nn_metric=metric)
                            ev = evaluate(tight, sol)
                            self.assertTrue(ev.feasible, ev.violations)
                            self.assertEqual(ev.served, 15)
                            # Without the shift limit the same solver builds
                            # routes that come back after the 150 minutes.
                            relaxed = solve(loose, solver, improve=improve, nn_metric=metric)
                            late = [v for v in evaluate(tight, relaxed).violations
                                    if "after the end of the shift" in v]
                            self.assertTrue(late)


class InfeasibleInputTest(unittest.TestCase):
    def test_demand_above_capacity(self):
        sc = make_scenario([(1, 0), (2, 0)], demands=[3, 50], capacity=10)
        for solver in ("nearest", "savings"):
            with self.assertRaises(InfeasibleScenarioError) as ctx:
                solve(sc, solver)
            self.assertEqual(len(ctx.exception.problems), 1)
            self.assertIn("customer 2 demand 50 exceeds vehicle capacity 10", str(ctx.exception))

    def test_window_closes_before_arrival(self):
        sc = make_scenario([(30, 0)], windows=[(0, 10)])
        with self.assertRaisesRegex(InfeasibleScenarioError, "before its due time"):
            solve(sc, "nearest")

    def test_cannot_return_before_end_of_shift(self):
        sc = make_scenario([(30, 0)], services=[20], shift=70)
        with self.assertRaisesRegex(InfeasibleScenarioError, "end of the shift"):
            solve(sc, "savings")

    def test_unknown_solver_or_metric(self):
        sc = square_scenario()
        with self.assertRaises(ValueError):
            solve(sc, "genetic")
        with self.assertRaises(ValueError):
            solve(sc, "nearest", nn_metric="angle")

    def test_empty_scenario(self):
        sc = make_scenario([])
        for solver in ("nearest", "savings"):
            ev = evaluate(sc, solve(sc, solver, improve=True))
            self.assertTrue(ev.feasible)
            self.assertEqual(ev.vehicles_used, 0)
            self.assertTrue(math.isclose(ev.total_distance, 0.0))


if __name__ == "__main__":
    unittest.main()
