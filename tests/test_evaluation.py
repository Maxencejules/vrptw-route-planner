import unittest

import support  # noqa: F401
from support import make_scenario

from vrptw import Instance, Solution, evaluate, generate, solve


def two_stop_scenario(**overrides):
    # Speed 60 km/h: one kilometre takes one minute.
    params = dict(
        windows=[(10, 20), (0, 100)],
        services=[5, 2],
        demands=[4, 3],
        capacity=10,
        vehicles=1,
        shift=60,
    )
    params.update(overrides)
    return make_scenario([(3, 0), (3, 4)], **params)


class TimelineTest(unittest.TestCase):
    def test_timeline_values(self):
        sc = two_stop_scenario()
        ev = evaluate(sc, Solution(routes=[[1, 2]]))
        self.assertTrue(ev.feasible, ev.violations)
        self.assertAlmostEqual(ev.total_distance, 12.0)
        (route,) = ev.routes
        # Leaves at 7 so that it reaches customer 1 exactly when it opens (10).
        self.assertAlmostEqual(route.leave_depot, 7.0)
        s1, s2 = route.stops
        self.assertEqual((s1.customer, s2.customer), (1, 2))
        self.assertAlmostEqual(s1.arrival, 10.0)
        self.assertAlmostEqual(s1.wait, 0.0)
        self.assertAlmostEqual(s1.start, 10.0)
        self.assertAlmostEqual(s1.departure, 15.0)
        self.assertAlmostEqual(s2.arrival, 19.0)
        self.assertAlmostEqual(s2.start, 19.0)
        self.assertAlmostEqual(s2.departure, 21.0)
        self.assertAlmostEqual(route.back_at_depot, 26.0)
        self.assertEqual((s1.load, s2.load), (4, 7))
        self.assertEqual(route.load, 7)

    def test_empty_routes_are_ignored(self):
        sc = two_stop_scenario()
        ev = evaluate(sc, Solution(routes=[[], [1, 2], []]))
        self.assertTrue(ev.feasible, ev.violations)
        self.assertEqual(ev.vehicles_used, 1)
        self.assertEqual(len(ev.routes), 1)
        self.assertAlmostEqual(ev.total_distance, 12.0)

    def test_later_departure_removes_waiting_at_a_later_stop(self):
        # Leaving at 0 would mean waiting 9 minutes at customer 1, the second
        # stop. Customer 2 stays open until 100, so the vehicle leaves at 9
        # instead and comes back at the same time.
        sc = two_stop_scenario(windows=[(20, 30), (0, 100)])
        ev = evaluate(sc, Solution(routes=[[2, 1]]))
        self.assertTrue(ev.feasible, ev.violations)
        route = ev.routes[0]
        s2, s1 = route.stops
        self.assertAlmostEqual(route.leave_depot, 9.0)
        self.assertAlmostEqual(s2.arrival, 14.0)
        self.assertAlmostEqual(s2.wait, 0.0)
        self.assertAlmostEqual(s2.departure, 16.0)
        self.assertAlmostEqual(s1.arrival, 20.0)
        self.assertAlmostEqual(s1.wait, 0.0)
        self.assertAlmostEqual(s1.start, 20.0)
        self.assertAlmostEqual(route.back_at_depot, 28.0)

    def test_waiting_that_no_departure_time_removes(self):
        # Customer 2 must start by 8, so the vehicle leaves at 3 at the
        # latest and 6 of the 9 minutes of waiting at customer 1 remain.
        sc = two_stop_scenario(windows=[(20, 30), (0, 8)])
        ev = evaluate(sc, Solution(routes=[[2, 1]]))
        self.assertTrue(ev.feasible, ev.violations)
        route = ev.routes[0]
        s2, s1 = route.stops
        self.assertAlmostEqual(route.leave_depot, 3.0)
        self.assertAlmostEqual(s2.start, 8.0)
        self.assertAlmostEqual(s1.arrival, 14.0)
        self.assertAlmostEqual(s1.wait, 6.0)
        self.assertAlmostEqual(s1.start, 20.0)
        self.assertAlmostEqual(route.back_at_depot, 28.0)

    def test_late_stop_is_not_made_later(self):
        # Customer 1 is reached at 3 even when leaving at 0, after its due
        # time 2, so the departure is not delayed and the 18-minute wait at
        # customer 2 stays.
        sc = two_stop_scenario(windows=[(0, 2), (30, 100)])
        ev = evaluate(sc, Solution(routes=[[1, 2]]))
        self.assertFalse(ev.feasible)
        route = ev.routes[0]
        self.assertAlmostEqual(route.leave_depot, 0.0)
        self.assertAlmostEqual(route.stops[0].start, 3.0)
        self.assertAlmostEqual(route.stops[1].wait, 18.0)
        self.assertEqual(
            ev.violations, ("vehicle 1: customer 1 reached at 3.0, after its due time 2",)
        )

    def test_departure_is_as_late_as_possible_on_generated_plans(self):
        # Independent check on solver output: the reported departure keeps
        # every stop on time and the return unchanged, and leaving a little
        # later would break a time window or delay the return, unless the
        # route has no waiting left at all.
        for layout in ("uniform", "clustered"):
            for seed in range(1, 5):
                sc = generate(customers=25, layout=layout, seed=seed)
                inst = Instance(sc)
                for solver in ("nearest", "savings"):
                    ev = evaluate(sc, solve(sc, solver, improve=True), inst)
                    self.assertTrue(ev.feasible, ev.violations)
                    for route in ev.routes:
                        nodes = [inst.node_of[c] for c in route.customers]
                        with self.subTest(layout=layout, seed=seed, solver=solver,
                                          vehicle=route.vehicle):
                            starts, back = simulate(inst, nodes, route.leave_depot)
                            self.assertTrue(
                                all(s <= inst.due[n] + 1e-6 for s, n in zip(starts, nodes))
                            )
                            self.assertAlmostEqual(back, simulate(inst, nodes, 0.0)[1])
                            self.assertAlmostEqual(back, route.back_at_depot)
                            if sum(s.wait for s in route.stops) < 1e-6:
                                continue
                            starts, later_back = simulate(inst, nodes, route.leave_depot + 0.01)
                            late = any(s > inst.due[n] + 1e-6 for s, n in zip(starts, nodes))
                            self.assertTrue(late or later_back > back + 1e-6)


def simulate(inst, nodes, leave):
    """Service start times and return time for a departure at ``leave``."""
    clock, prev, starts = leave, 0, []
    for node in nodes:
        start = max(clock + inst.travel[prev][node], inst.ready[node])
        starts.append(start)
        clock, prev = start + inst.service[node], node
    return starts, clock + inst.travel[prev][0]


class ViolationTest(unittest.TestCase):
    def assertViolation(self, sc, routes, fragment):
        ev = evaluate(sc, Solution(routes=routes))
        self.assertFalse(ev.feasible)
        self.assertTrue(
            any(fragment in v for v in ev.violations),
            f"{fragment!r} not in {ev.violations}",
        )
        return ev

    def test_capacity(self):
        self.assertViolation(two_stop_scenario(capacity=6), [[1, 2]], "exceeds capacity")

    def test_due_time(self):
        # Visiting customer 2 first reaches customer 1 at 11, after its due time 10.
        sc = two_stop_scenario(windows=[(0, 10), (0, 100)])
        self.assertViolation(sc, [[2, 1]], "after its due time")

    def test_end_of_shift(self):
        self.assertViolation(two_stop_scenario(shift=25), [[1, 2]], "after the end of the shift")

    def test_missing_customer(self):
        self.assertViolation(two_stop_scenario(), [[1]], "not served: 2")

    def test_duplicate_visit(self):
        self.assertViolation(two_stop_scenario(vehicles=2), [[1, 2], [2]], "more than once")

    def test_unknown_customer(self):
        self.assertViolation(two_stop_scenario(), [[1, 2, 42]], "unknown customer id 42")

    def test_too_many_routes(self):
        self.assertViolation(two_stop_scenario(vehicles=1), [[1], [2]], "vehicles available")


if __name__ == "__main__":
    unittest.main()
