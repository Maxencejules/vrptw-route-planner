"""Independent route audit and bounded exhaustive reference.

Uses raw model fields and Euclidean geometry, never Instance, evaluate,
latest_departure or solver feasibility/cost helpers. Earliest departure is
enough to decide feasibility: delaying cannot make a due time or return
earlier when travel/service times are nonnegative and waiting is allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations, product
from math import fsum, hypot, isfinite
from typing import Sequence

from .model import Scenario

TOLERANCE = 1e-6  # minutes/capacity units; independent of solver constants


@dataclass(frozen=True)
class Audit:
    feasible: bool
    violations: tuple[str, ...]
    total_distance: float
    vehicles_used: int


def audit_routes(
    scenario: Scenario,
    routes: Sequence[Sequence[int]],
    *,
    claimed_distance: float | None = None,
    distance_tolerance: float = TOLERANCE,
) -> Audit:
    """Check coverage, fleet, capacity, service-start windows, return and cost.

    Empty routes use no vehicles. Distances remain unrounded. A rejected
    plan's distance is diagnostic only, especially if ids are invalid.
    """
    if isinstance(distance_tolerance, bool) or not isinstance(distance_tolerance, (int, float)):
        raise ValueError("distance_tolerance must be a finite nonnegative number")
    try:
        valid_tolerance = isfinite(distance_tolerance) and distance_tolerance >= 0
    except OverflowError:
        valid_tolerance = False
    if not valid_tolerance:
        raise ValueError("distance_tolerance must be a finite nonnegative number")
    customers = {c.id: c for c in scenario.customers}
    seen: set[int] = set()
    issues: list[str] = []
    legs: list[float] = []
    used = 0
    minutes_per_unit = 60.0 / scenario.fleet.speed
    for route in routes:
        if not route:
            continue
        used += 1
        clock = load = 0.0
        x, y = scenario.depot.x, scenario.depot.y
        for cid in route:
            if isinstance(cid, bool) or not isinstance(cid, int) or cid not in customers:
                issues.append(f"route {used}: unknown customer {cid!r}")
                continue
            if cid in seen:
                issues.append(f"customer {cid} visited more than once")
            seen.add(cid)
            c = customers[cid]
            leg = hypot(c.x - x, c.y - y)
            legs.append(leg)
            clock = max(clock + leg * minutes_per_unit, c.ready)
            if clock > c.due + TOLERANCE:
                issues.append(f"route {used}: customer {cid} starts after due time")
            clock += c.service
            load += c.demand
            x, y = c.x, c.y
        home = hypot(x - scenario.depot.x, y - scenario.depot.y)
        legs.append(home)
        clock += home * minutes_per_unit
        if load > scenario.fleet.capacity + TOLERANCE:
            issues.append(f"route {used}: capacity exceeded")
        if not isfinite(clock) or clock > scenario.fleet.shift_length + TOLERANCE:
            issues.append(f"route {used}: return after shift")
    if used > scenario.fleet.vehicles:
        issues.append("fleet size exceeded")
    missing = sorted(customers.keys() - seen)
    if missing:
        issues.append(f"customers not served: {missing}")
    try:
        total = fsum(legs)
    except OverflowError:
        total = float("inf")
    if not isfinite(total):
        issues.append("non-finite total distance")
    if claimed_distance is not None:
        if (isinstance(claimed_distance, bool)
                or not isinstance(claimed_distance, (int, float))):
            issues.append("claimed distance must be a finite number")
        else:
            try:
                valid = isfinite(claimed_distance)
            except OverflowError:
                valid = False
            if not valid or abs(total - claimed_distance) > distance_tolerance:
                issues.append("claimed distance differs from independently recomputed distance")
    return Audit(not issues, tuple(issues), total, used)


@dataclass(frozen=True)
class ExhaustiveResult:
    distance: float | None
    routes: tuple[tuple[int, ...], ...]
    plans_considered: int


def exhaustive_tiny(scenario: Scenario) -> ExhaustiveResult:
    """Enumerate all orders and route cuts, up to six customers.

    Covers every ordered partition (with harmless duplicates from route
    ordering). This certifies the minimum only for this tiny floating-point
    distance-only model and tolerance; it is not a large-instance solver.
    """
    ids = [c.id for c in scenario.customers]
    if len(ids) > 6:
        raise ValueError("exhaustive reference is limited to six customers")
    if not ids:
        return ExhaustiveResult(0.0, (), 1)
    best: float | None = None
    best_routes: tuple[tuple[int, ...], ...] = ()
    count = 0
    for order in permutations(ids):
        for cuts in product((False, True), repeat=len(ids) - 1):
            count += 1
            routes, current = [], [order[0]]
            for cid, cut in zip(order[1:], cuts):
                if cut:
                    routes.append(current)
                    current = [cid]
                else:
                    current.append(cid)
            routes.append(current)
            if len(routes) > scenario.fleet.vehicles:
                continue
            checked = audit_routes(scenario, routes)
            if checked.feasible and (best is None or checked.total_distance < best):
                best = checked.total_distance
                best_routes = tuple(tuple(r) for r in routes)
    return ExhaustiveResult(best, best_routes, count)
