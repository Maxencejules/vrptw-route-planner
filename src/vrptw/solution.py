"""Solutions, their evaluation, and the solution JSON format.

A solution lists routes as sequences of customer *ids* (not solver nodes),
so a solution file can be read and checked against its scenario without
knowing anything about how it was produced.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .instance import EPS, Instance
from .model import Scenario

FORMAT_NAME = "vrptw-solution"
FORMAT_VERSION = 1


class SolutionError(ValueError):
    """A solution file is malformed."""


@dataclass
class Solution:
    routes: list[list[int]]
    unassigned: list[int] = field(default_factory=list)
    solver: str = ""
    improved: bool = False
    options: dict[str, Any] = field(default_factory=dict)
    search: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Stop:
    customer: int
    arrival: float
    wait: float
    start: float
    departure: float
    load: float        # cumulative demand delivered on this route after the stop


@dataclass(frozen=True)
class RouteTimeline:
    vehicle: int
    customers: tuple[int, ...]
    leave_depot: float
    back_at_depot: float
    distance: float
    load: float
    stops: tuple[Stop, ...]


@dataclass(frozen=True)
class Evaluation:
    feasible: bool
    violations: tuple[str, ...]
    total_distance: float
    vehicles_used: int
    vehicles_available: int
    served: int
    customers: int
    routes: tuple[RouteTimeline, ...]


def latest_departure(inst: Instance, nodes: list[int]) -> float:
    """Latest time the vehicle can leave the depot for this stop order.

    Starting from the schedule that leaves at time 0, a later departure
    first uses up waiting time. Leaving ``delta`` minutes later pushes the
    service start at stop ``k`` back by ``max(0, delta - W_k)``, where
    ``W_k`` is the waiting accumulated up to and including stop ``k``. The
    departure is delayed as far as possible while

    * no stop that is on time starts after its due time
      (``delta <= W_k + due_k - start_k``);
    * no stop that is already late starts any later (``delta <= W_k``);
    * the return to the depot does not move (``delta <= W_n``).

    The result is the forward time slack of the route, capped by its total
    waiting (Savelsbergh, 1992). Any wait left in the schedule could only be
    removed by starting some stop after its due time, that is, only by a
    different stop order.
    """
    travel, ready, due, service = inst.travel, inst.ready, inst.due, inst.service
    clock, prev = 0.0, 0
    waited = 0.0
    slack = 0.0
    for pos, node in enumerate(nodes):
        arrival = clock + travel[prev][node]
        start = max(arrival, ready[node])
        waited += start - arrival
        bound = waited + max(0.0, due[node] - start)
        slack = bound if pos == 0 else min(slack, bound)
        clock, prev = start + service[node], node
    return min(waited, slack)


def timeline(inst: Instance, nodes: list[int], vehicle: int) -> RouteTimeline:
    """Arrival, service start and departure for every stop of one route.

    The vehicle leaves the depot at ``latest_departure``: as late as it can
    without starting an on-time stop after its due time, making a late stop
    later, or coming back to the depot later. Waiting that a later
    departure could remove is therefore not shown. The return time, the
    distance and the feasibility of the route are the same as for a
    departure at time 0.
    """
    travel, ready, service = inst.travel, inst.ready, inst.service
    leave = latest_departure(inst, nodes)
    clock, prev, load = leave, 0, 0.0
    stops = []
    for node in nodes:
        arrival = clock + travel[prev][node]
        start = max(arrival, ready[node])
        departure = start + service[node]
        load += inst.demand[node]
        stops.append(
            Stop(inst.ids[node], arrival, start - arrival, start, departure, load)
        )
        clock, prev = departure, node
    back = clock + travel[prev][0] if nodes else leave
    return RouteTimeline(
        vehicle=vehicle,
        customers=tuple(inst.ids[n] for n in nodes),
        leave_depot=leave,
        back_at_depot=back,
        distance=inst.route_distance(nodes),
        load=load,
        stops=tuple(stops),
    )


def evaluate(scenario: Scenario, solution: Solution, inst: Instance | None = None) -> Evaluation:
    """Check every constraint and build per-route timelines.

    Checked: each customer served exactly once, no unknown ids, vehicle
    capacity, service starting no later than the due time, return to the
    depot by the end of the shift, and no more routes than vehicles.
    Empty routes are ignored.
    """
    inst = inst or Instance(scenario)
    violations: list[str] = []
    seen: dict[int, int] = {}
    timelines = []
    vehicle = 0
    for route in solution.routes:
        if not route:
            continue
        vehicle += 1
        nodes = []
        for cid in route:
            node = inst.node_of.get(cid) if isinstance(cid, int) and not isinstance(cid, bool) else None
            if node is None:
                violations.append(f"vehicle {vehicle}: unknown customer id {cid}")
                continue
            if cid in seen:
                violations.append(
                    f"customer {cid} is visited more than once "
                    f"(vehicles {seen[cid]} and {vehicle})"
                )
            else:
                seen[cid] = vehicle
            nodes.append(node)
        tl = timeline(inst, nodes, vehicle)
        timelines.append(tl)
        if tl.load > inst.capacity + EPS:
            violations.append(
                f"vehicle {vehicle}: load {tl.load:g} exceeds capacity {inst.capacity:g}"
            )
        for stop in tl.stops:
            due = scenario.customer(stop.customer).due
            if stop.start > due + EPS:
                violations.append(
                    f"vehicle {vehicle}: customer {stop.customer} reached at "
                    f"{stop.start:.1f}, after its due time {due:g}"
                )
        if tl.back_at_depot > inst.shift + EPS:
            violations.append(
                f"vehicle {vehicle}: back at depot at {tl.back_at_depot:.1f}, "
                f"after the end of the shift {inst.shift:g}"
            )
    missing = [c.id for c in scenario.customers if c.id not in seen]
    if missing:
        listed = ", ".join(str(m) for m in missing)
        violations.append(f"{len(missing)} customer(s) not served: {listed}")
    if vehicle > inst.vehicles:
        violations.append(f"{vehicle} routes need more than the {inst.vehicles} vehicles available")
    return Evaluation(
        feasible=not violations,
        violations=tuple(violations),
        total_distance=sum(t.distance for t in timelines),
        vehicles_used=vehicle,
        vehicles_available=inst.vehicles,
        served=len(seen),
        customers=len(scenario.customers),
        routes=tuple(timelines),
    )


# ------------------------------------------------------------------ JSON
def _r(value: float) -> float:
    return round(value, 3)


def solution_to_dict(scenario: Scenario, solution: Solution, ev: Evaluation) -> dict[str, Any]:
    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "scenario": scenario.name,
        "solver": solution.solver,
        "improved": solution.improved,
        "options": dict(solution.options),
        "routes": [list(r) for r in solution.routes if r],
        "unassigned": list(solution.unassigned),
        "summary": {
            "feasible": ev.feasible,
            "violations": list(ev.violations),
            "total_distance": _r(ev.total_distance),
            "vehicles_used": ev.vehicles_used,
            "vehicles_available": ev.vehicles_available,
        },
        "local_search": solution.search or None,
        "timeline": [
            {
                "vehicle": t.vehicle,
                "leave_depot": _r(t.leave_depot),
                "back_at_depot": _r(t.back_at_depot),
                "distance": _r(t.distance),
                "load": t.load,
                "stops": [
                    {
                        "customer": s.customer,
                        "arrival": _r(s.arrival),
                        "wait": _r(s.wait),
                        "start": _r(s.start),
                        "departure": _r(s.departure),
                        "load": s.load,
                    }
                    for s in t.stops
                ],
            }
            for t in ev.routes
        ],
    }


def solution_from_dict(data: Mapping[str, Any]) -> Solution:
    """Read a solution document. Only ``routes`` is required; ``format``
    may be left out, but if it is present it must be ``vrptw-solution``."""
    if not isinstance(data, Mapping) or data.get("format", FORMAT_NAME) != FORMAT_NAME:
        raise SolutionError(f"not a {FORMAT_NAME} document")
    routes = data.get("routes")
    if not isinstance(routes, list) or not all(isinstance(r, list) for r in routes):
        raise SolutionError("'routes' must be a list of lists of customer ids")
    for r in routes:
        for cid in r:
            if isinstance(cid, bool) or not isinstance(cid, int):
                raise SolutionError(f"customer id {cid!r} is not an integer")
    unassigned = data.get("unassigned")
    if unassigned is None:
        unassigned = []
    if not isinstance(unassigned, list) or any(
        isinstance(cid, bool) or not isinstance(cid, int) for cid in unassigned
    ):
        raise SolutionError("'unassigned' must be a list of customer ids")
    extras = {}
    for key in ("options", "local_search"):
        value = data.get(key)
        if value is None:
            value = {}
        if not isinstance(value, Mapping):
            raise SolutionError(f"'{key}' must be an object")
        extras[key] = dict(value)
    _check_search(extras["local_search"])
    solver = data.get("solver", "")
    if not isinstance(solver, str):
        raise SolutionError("'solver' must be a string")
    improved = data.get("improved", False)
    if not isinstance(improved, bool):
        raise SolutionError("'improved' must be true or false")
    return Solution(
        routes=[list(r) for r in routes],
        unassigned=list(unassigned),
        solver=solver,
        improved=improved,
        options=extras["options"],
        search=extras["local_search"],
    )


def _check_search(search: Mapping[str, Any]) -> None:
    """Check the fields of a ``local_search`` object that reports display."""
    moves = search.get("moves", {})
    if not isinstance(moves, Mapping) or any(
        not isinstance(k, str) or isinstance(v, bool) or not isinstance(v, int) or v < 0
        for k, v in moves.items()
    ):
        raise SolutionError("'local_search.moves' must map move names to counts")
    for key in ("start_distance", "end_distance"):
        value = search.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise SolutionError(f"'local_search.{key}' must be a finite number")


def save_solution(path: str | Path, scenario: Scenario, solution: Solution, ev: Evaluation) -> None:
    text = json.dumps(solution_to_dict(scenario, solution, ev), indent=2)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text + "\n", encoding="utf-8")


def load_solution(path: str | Path) -> Solution:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SolutionError(f"invalid JSON: {exc}") from None
    return solution_from_dict(data)
