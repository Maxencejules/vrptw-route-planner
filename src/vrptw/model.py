"""Scenario model: depot, customers and fleet, plus JSON reading and writing.

Units used everywhere in the package:

* coordinates and distances are kilometres on a flat plane;
* times are minutes counted from the start of the shift (time 0);
* vehicle speed is kilometres per hour.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

FORMAT_NAME = "vrptw-scenario"
FORMAT_VERSION = 1


class ScenarioError(ValueError):
    """The scenario data is malformed or internally inconsistent."""


@dataclass(frozen=True)
class Customer:
    """A delivery stop.

    ``ready`` and ``due`` bound the moment service may *start*. A vehicle that
    arrives before ``ready`` waits; arriving after ``due`` is not allowed.
    """

    id: int
    x: float
    y: float
    demand: float
    ready: float
    due: float
    service: float


@dataclass(frozen=True)
class Depot:
    x: float
    y: float


@dataclass(frozen=True)
class Fleet:
    """Identical vehicles that may leave the depot from time 0 on and must be
    back by ``shift_length`` minutes."""

    vehicles: int
    capacity: float
    speed: float
    shift_length: float


@dataclass
class Scenario:
    name: str
    depot: Depot
    fleet: Fleet
    customers: list[Customer]
    generator: dict[str, Any] = field(default_factory=dict)
    _by_id: dict[int, Customer] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )

    def __post_init__(self) -> None:
        self.customers = list(self.customers)
        _validate(self)
        self._by_id = {c.id: c for c in self.customers}

    def customer(self, customer_id: int) -> Customer:
        try:
            return self._by_id[customer_id]
        except KeyError:
            raise KeyError(f"no customer with id {customer_id}") from None

    @property
    def total_demand(self) -> float:
        return sum(c.demand for c in self.customers)

    # ------------------------------------------------------------------ JSON
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "name": self.name,
            "units": {"distance": "km", "time": "min", "speed": "km/h"},
            "depot": {"x": self.depot.x, "y": self.depot.y},
            "fleet": {
                "vehicles": self.fleet.vehicles,
                "capacity": self.fleet.capacity,
                "speed": self.fleet.speed,
                "shift_length": self.fleet.shift_length,
            },
        }
        if self.generator:
            data["generator"] = dict(self.generator)
        data["customers"] = [
            {
                "id": c.id,
                "x": c.x,
                "y": c.y,
                "demand": c.demand,
                "ready": c.ready,
                "due": c.due,
                "service": c.service,
            }
            for c in self.customers
        ]
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Scenario":
        if not isinstance(data, Mapping):
            raise ScenarioError("scenario must be a JSON object")
        fmt = data.get("format", FORMAT_NAME)
        if fmt != FORMAT_NAME:
            raise ScenarioError(f"unexpected format {fmt!r}, expected {FORMAT_NAME!r}")
        version = data.get("version", FORMAT_VERSION)
        if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= FORMAT_VERSION:
            raise ScenarioError(f"unsupported scenario version {version!r}")

        depot_raw = _section(data, "depot")
        fleet_raw = _section(data, "fleet")
        depot = Depot(
            x=_number(depot_raw, "x", "depot"),
            y=_number(depot_raw, "y", "depot"),
        )
        vehicles = fleet_raw.get("vehicles")
        if isinstance(vehicles, bool) or not isinstance(vehicles, int):
            raise ScenarioError("fleet.vehicles must be an integer")
        fleet = Fleet(
            vehicles=vehicles,
            capacity=_number(fleet_raw, "capacity", "fleet"),
            speed=_number(fleet_raw, "speed", "fleet"),
            shift_length=_number(fleet_raw, "shift_length", "fleet"),
        )

        raw_customers = data.get("customers")
        if not isinstance(raw_customers, list):
            raise ScenarioError("'customers' must be a list")
        customers = []
        for pos, raw in enumerate(raw_customers):
            where = f"customers[{pos}]"
            if not isinstance(raw, Mapping):
                raise ScenarioError(f"{where} must be an object")
            cid = raw.get("id")
            if isinstance(cid, bool) or not isinstance(cid, int):
                raise ScenarioError(f"{where}.id must be an integer")
            customers.append(
                Customer(
                    id=cid,
                    x=_number(raw, "x", where),
                    y=_number(raw, "y", where),
                    demand=_number(raw, "demand", where),
                    ready=_number(raw, "ready", where, default=0),
                    due=_number(raw, "due", where, default=fleet.shift_length),
                    service=_number(raw, "service", where, default=0),
                )
            )
        generator = data.get("generator")
        if generator is None:
            generator = {}
        if not isinstance(generator, Mapping):
            raise ScenarioError("'generator' must be an object when present")
        name = data.get("name", "unnamed")
        if not isinstance(name, str):
            raise ScenarioError("'name' must be a string when present")
        return cls(
            name=name,
            depot=depot,
            fleet=fleet,
            customers=customers,
            generator=dict(generator),
        )

    def dumps(self) -> str:
        """Serialise to JSON text: one line per top-level member and one line
        per customer, which keeps files short and easy to diff."""
        members = []
        for key, value in self.to_dict().items():
            if key == "customers" and value:
                rows = ",\n".join("    " + json.dumps(c) for c in value)
                text = "[\n" + rows + "\n  ]"
            else:
                text = json.dumps(value)
            members.append(f"  {json.dumps(key)}: {text}")
        return "{\n" + ",\n".join(members) + "\n}\n"

    @classmethod
    def loads(cls, text: str) -> "Scenario":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ScenarioError(f"invalid JSON: {exc}") from None
        return cls.from_dict(data)


def load_scenario(path: str | Path) -> Scenario:
    return Scenario.loads(Path(path).read_text(encoding="utf-8"))


def save_scenario(scenario: Scenario, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(scenario.dumps(), encoding="utf-8")


# ---------------------------------------------------------------- helpers
def _section(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise ScenarioError(f"'{key}' must be an object")
    return value


_MISSING = object()


def _number(raw: Mapping[str, Any], key: str, where: str, default: Any = _MISSING) -> float:
    value = raw.get(key, default)
    if value is _MISSING:
        raise ScenarioError(f"{where}.{key} is missing")
    return _finite_number(value, f"{where}.{key}")


def _finite_number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScenarioError(f"{where} must be a number")
    try:
        finite = math.isfinite(value)
    except OverflowError:  # an int too large to convert to float
        finite = False
    if not finite:
        raise ScenarioError(f"{where} must be finite")
    return value


def _validate(s: Scenario) -> None:
    f = s.fleet
    if not isinstance(s.name, str):
        raise ScenarioError("name must be a string")
    if isinstance(f.vehicles, bool) or not isinstance(f.vehicles, int):
        raise ScenarioError("fleet.vehicles must be an integer")
    for name in ("x", "y"):
        _finite_number(getattr(s.depot, name), f"depot.{name}")
    for name in ("capacity", "speed", "shift_length"):
        _finite_number(getattr(f, name), f"fleet.{name}")
    if f.vehicles < 1:
        raise ScenarioError("fleet.vehicles must be at least 1")
    if f.capacity <= 0:
        raise ScenarioError("fleet.capacity must be positive")
    if f.speed <= 0:
        raise ScenarioError("fleet.speed must be positive")
    if f.shift_length <= 0:
        raise ScenarioError("fleet.shift_length must be positive")
    seen: set[int] = set()
    for c in s.customers:
        if isinstance(c.id, bool) or not isinstance(c.id, int) or c.id < 1:
            raise ScenarioError(f"customer id {c.id} must be a positive integer")
        for name in ("x", "y", "demand", "ready", "due", "service"):
            _finite_number(getattr(c, name), f"customer {c.id}.{name}")
        if c.id in seen:
            raise ScenarioError(f"duplicate customer id {c.id}")
        seen.add(c.id)
        if c.demand < 0:
            raise ScenarioError(f"customer {c.id}: demand must not be negative")
        if c.service < 0:
            raise ScenarioError(f"customer {c.id}: service time must not be negative")
        if c.ready > c.due:
            raise ScenarioError(
                f"customer {c.id}: time window [{c.ready}, {c.due}] is empty"
            )
