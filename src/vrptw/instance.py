"""Numeric view of a scenario that the solvers work on.

Nodes are integers: node 0 is the depot and node ``k`` (k >= 1) is the k-th
customer in scenario order. A route is a list of customer nodes; the depot at
both ends is implicit.
"""

from __future__ import annotations

import math
from typing import Sequence

from .model import Scenario

# Tolerance for comparing times and loads that come out of float arithmetic.
EPS = 1e-6


class InfeasibleScenarioError(ValueError):
    """At least one customer cannot be served even by a dedicated vehicle."""

    def __init__(self, problems: Sequence[str]):
        self.problems = list(problems)
        super().__init__("scenario cannot be served: " + "; ".join(self.problems))


class Instance:
    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        fleet = scenario.fleet
        customers = scenario.customers
        self.size = len(customers) + 1
        self.capacity = fleet.capacity
        self.shift = fleet.shift_length
        self.vehicles = fleet.vehicles

        self.ids: list[int] = [0] + [c.id for c in customers]
        self.node_of: dict[int, int] = {c.id: k for k, c in enumerate(customers, 1)}
        self.demand: list[float] = [0] + [c.demand for c in customers]
        self.ready: list[float] = [0] + [c.ready for c in customers]
        self.due: list[float] = [fleet.shift_length] + [c.due for c in customers]
        self.service: list[float] = [0] + [c.service for c in customers]

        xs = [scenario.depot.x] + [c.x for c in customers]
        ys = [scenario.depot.y] + [c.y for c in customers]
        self.dist: list[list[float]] = [
            [math.hypot(xs[i] - xs[j], ys[i] - ys[j]) for j in range(self.size)]
            for i in range(self.size)
        ]
        minutes_per_km = 60.0 / fleet.speed
        self.travel: list[list[float]] = [
            [d * minutes_per_km for d in row] for row in self.dist
        ]

    # ----------------------------------------------------------- routes
    def route_load(self, route: Sequence[int]) -> float:
        return sum(self.demand[i] for i in route)

    def route_distance(self, route: Sequence[int]) -> float:
        if not route:
            return 0.0
        d = self.dist
        total = d[0][route[0]] + d[route[-1]][0]
        for a, b in zip(route, route[1:]):
            total += d[a][b]
        return total

    def return_time(self, route: Sequence[int]) -> float | None:
        """Time the vehicle is back at the depot, or ``None`` if some stop
        would be reached after its due time. Capacity is not checked here."""
        t = 0.0
        prev = 0
        travel, ready, due, service = self.travel, self.ready, self.due, self.service
        for node in route:
            t += travel[prev][node]
            if t > due[node] + EPS:
                return None
            if t < ready[node]:
                t = ready[node]
            t += service[node]
            prev = node
        return t + travel[prev][0]

    def route_feasible(self, route: Sequence[int]) -> bool:
        if self.route_load(route) > self.capacity + EPS:
            return False
        end = self.return_time(route)
        return end is not None and end <= self.shift + EPS

    def total_distance(self, routes: Sequence[Sequence[int]]) -> float:
        return sum(self.route_distance(r) for r in routes)

    # ---------------------------------------------------------- scenario
    def unservable(self) -> list[str]:
        """Describe every customer that no plan could serve."""
        problems = []
        for node in range(1, self.size):
            cid = self.ids[node]
            if self.demand[node] > self.capacity + EPS:
                problems.append(
                    f"customer {cid} demand {self.demand[node]:g} exceeds "
                    f"vehicle capacity {self.capacity:g}"
                )
                continue
            arrive = self.travel[0][node]
            if arrive > self.due[node] + EPS:
                problems.append(
                    f"customer {cid} cannot be reached before its due time "
                    f"{self.due[node]:g} (earliest arrival {arrive:.1f})"
                )
                continue
            back = max(arrive, self.ready[node]) + self.service[node] + self.travel[node][0]
            if back > self.shift + EPS:
                problems.append(
                    f"customer {cid} cannot be served with a return to the depot "
                    f"by the end of the shift {self.shift:g} (earliest return {back:.1f})"
                )
        return problems

    def require_servable(self) -> None:
        problems = self.unservable()
        if problems:
            raise InfeasibleScenarioError(problems)
