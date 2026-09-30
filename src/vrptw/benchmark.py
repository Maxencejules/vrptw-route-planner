"""Strict Solomon text importer for the model's supported depot convention."""

from __future__ import annotations

from pathlib import Path

from .model import Customer, Depot, Fleet, Scenario, ScenarioError


def load_solomon(path: str | Path) -> Scenario:
    """Load all customers; no truncation or distance/travel-time rounding.

    Benchmark coordinates are numerical distance units. Setting speed=60
    embeds travel time == distance in our km/min model without conversion.
    Depot ready time, demand and service must be zero, and its due time
    becomes the shift limit. Other depot conventions cannot be represented.
    """
    lines = [line.strip() for line in Path(path).read_text(encoding="ascii").splitlines()
             if line.strip()]
    try:
        vehicle = lines.index("VEHICLE")
        customer = lines.index("CUSTOMER")
        if vehicle != 1 or customer != vehicle + 3:
            raise ValueError("unexpected section order")
        if lines[vehicle + 1].split() != ["NUMBER", "CAPACITY"]:
            raise ValueError("missing fleet heading")
        values = lines[vehicle + 2].split()
        if len(values) != 2 or not lines[customer + 1].startswith("CUST NO."):
            raise ValueError("invalid fleet or customer heading")
        fleet_count, capacity = int(values[0]), float(values[1])
        rows = []
        for line in lines[customer + 2:]:
            columns = line.split()
            if len(columns) != 7:
                raise ValueError("each customer must have seven columns")
            rows.append((int(columns[0]), *(float(v) for v in columns[1:])))
        if not rows or rows[0][0] != 0:
            raise ValueError("first row must be depot 0")
        _, x, y, demand, ready, due, service = rows[0]
        if demand != 0 or ready != 0 or service != 0:
            raise ValueError("depot demand, ready time and service must be zero")
        return Scenario(
            name=lines[0], depot=Depot(x, y),
            fleet=Fleet(fleet_count, capacity, 60.0, due),
            customers=[Customer(*row) for row in rows[1:]],
        )
    except (ValueError, IndexError) as exc:
        raise ScenarioError(f"invalid Solomon instance: {exc}") from None
