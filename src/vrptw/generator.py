"""Seeded generator for random routing scenarios.

Every customer is placed so that a dedicated vehicle could serve it on its
own: the time window always overlaps the interval between the earliest
possible arrival from the depot and the latest service start that still
allows a return before the end of the shift.
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, replace

from .model import Customer, Depot, Fleet, Scenario

LAYOUTS = ("uniform", "clustered")
DEPOT_POSITIONS = ("center", "corner")


@dataclass(frozen=True)
class GeneratorSettings:
    customers: int = 25
    layout: str = "uniform"
    seed: int = 1
    area: float = 50.0            # side of the square service region, km
    clusters: int = 4             # used by the clustered layout
    cluster_spread: float = 4.0   # standard deviation around a cluster centre, km
    depot: str = "center"
    demand: tuple[int, int] = (1, 10)
    service: tuple[int, int] = (5, 15)     # minutes
    window: tuple[int, int] = (60, 180)    # time-window width, minutes
    capacity: int = 60
    speed: float = 40.0                    # km/h
    shift_length: int = 480                # minutes
    vehicles: int | None = None            # None: derived from total demand

    def validate(self) -> None:
        for name in ("area", "cluster_spread", "speed"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be a finite number")
        if self.customers < 1:
            raise ValueError("customers must be at least 1")
        if self.layout not in LAYOUTS:
            raise ValueError(f"layout must be one of {', '.join(LAYOUTS)}")
        if self.depot not in DEPOT_POSITIONS:
            raise ValueError(f"depot must be one of {', '.join(DEPOT_POSITIONS)}")
        if self.area <= 0:
            raise ValueError("area must be positive")
        if self.layout == "clustered" and self.clusters < 1:
            raise ValueError("clusters must be at least 1")
        if self.cluster_spread < 0:
            raise ValueError("cluster_spread must not be negative")
        for name in ("demand", "service", "window"):
            lo, hi = getattr(self, name)
            if lo < 0 or lo > hi:
                raise ValueError(f"{name} range must satisfy 0 <= low <= high")
        if self.demand[1] > self.capacity:
            raise ValueError("the largest demand must not exceed the capacity")
        if self.capacity <= 0 or self.speed <= 0 or self.shift_length <= 0:
            raise ValueError("capacity, speed and shift_length must be positive")
        if self.vehicles is not None and self.vehicles < 1:
            raise ValueError("vehicles must be at least 1")


def default_vehicle_count(total_demand: float, capacity: float, customers: int) -> int:
    """Fleet size used when none is given.

    Deliberately generous: time windows can force far more routes than the
    capacity bound ``ceil(total_demand / capacity)`` suggests, and the
    fleet size is only an upper limit on the vehicles a plan may use.
    """
    lower = math.ceil(total_demand / capacity)
    return max(3, 2 * lower, math.ceil(customers / 3))


def generate(settings: GeneratorSettings | None = None, **overrides) -> Scenario:
    """Create a scenario. Keyword arguments override fields of ``settings``."""
    s = replace(settings or GeneratorSettings(), **overrides)
    s.validate()
    rng = random.Random(s.seed)

    if s.depot == "center":
        depot = Depot(s.area / 2, s.area / 2)
    else:
        depot = Depot(0.0, 0.0)

    points = _uniform_points(rng, s) if s.layout == "uniform" else _clustered_points(rng, s)
    minutes_per_km = 60.0 / s.speed

    customers = []
    for cid, (x, y) in enumerate(points, 1):
        demand = rng.randint(*s.demand)
        service = rng.randint(*s.service)
        width = rng.randint(*s.window)
        one_way = math.hypot(x - depot.x, y - depot.y) * minutes_per_km
        earliest = math.ceil(one_way)
        latest = math.floor(s.shift_length - service - one_way)
        if latest < earliest:
            raise ValueError(
                f"customer {cid} at ({x}, {y}) cannot be served within a "
                f"{s.shift_length}-minute shift; use a longer shift, a higher "
                "speed or a smaller area"
            )
        centre = rng.uniform(earliest, latest)
        ready = max(0, math.floor(centre - width / 2))
        due = min(latest, math.ceil(centre + width / 2))
        customers.append(Customer(cid, x, y, demand, ready, due, service))

    total_demand = sum(c.demand for c in customers)
    vehicles = s.vehicles or default_vehicle_count(total_demand, s.capacity, s.customers)
    fleet = Fleet(vehicles, s.capacity, s.speed, s.shift_length)

    meta = asdict(s)
    meta["vehicles"] = vehicles
    for key in ("demand", "service", "window"):
        meta[key] = list(meta[key])
    if s.layout != "clustered":
        meta.pop("clusters")
        meta.pop("cluster_spread")
    name = f"{s.layout}-n{s.customers}-seed{s.seed}"
    return Scenario(name=name, depot=depot, fleet=fleet, customers=customers, generator=meta)


def _uniform_points(rng: random.Random, s: GeneratorSettings) -> list[tuple[float, float]]:
    return [
        (round(rng.uniform(0, s.area), 2), round(rng.uniform(0, s.area), 2))
        for _ in range(s.customers)
    ]


def _clustered_points(rng: random.Random, s: GeneratorSettings) -> list[tuple[float, float]]:
    margin = 0.1 * s.area
    centres = [
        (rng.uniform(margin, s.area - margin), rng.uniform(margin, s.area - margin))
        for _ in range(s.clusters)
    ]
    points = []
    for _ in range(s.customers):
        cx, cy = rng.choice(centres)
        x = min(max(rng.gauss(cx, s.cluster_spread), 0.0), s.area)
        y = min(max(rng.gauss(cy, s.cluster_spread), 0.0), s.area)
        points.append((round(x, 2), round(y, 2)))
    return points
