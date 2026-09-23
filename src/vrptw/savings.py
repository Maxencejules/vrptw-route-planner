"""Clarke-Wright savings construction (parallel version) with time windows.

Start with one out-and-back route per customer. For every pair of customers
the saving ``d(0,i) + d(0,j) - d(i,j)`` is the distance removed by serving
them consecutively on one route. Pairs are processed from the largest saving
down; two routes are joined when ``i`` and ``j`` sit at ends of different
routes and the joined route passes the capacity, time-window and shift
checks. Because travel is symmetric, a route may be reversed to put ``i`` and
``j`` next to each other; the reversed route is checked like any other.

The fleet size is not enforced during construction. If the result needs more
routes than there are vehicles, the evaluation reports it.
"""

from __future__ import annotations

from .instance import EPS, Instance


def savings_list(inst: Instance) -> list[tuple[float, int, int]]:
    d = inst.dist
    pairs = [
        (d[0][i] + d[0][j] - d[i][j], i, j)
        for i in range(1, inst.size)
        for j in range(i + 1, inst.size)
    ]
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
    return pairs


def clarke_wright(inst: Instance) -> list[list[int]]:
    routes: dict[int, list[int]] = {k: [k] for k in range(1, inst.size)}
    load: dict[int, float] = {k: inst.demand[k] for k in range(1, inst.size)}
    owner = list(range(inst.size))  # owner[node] -> key of the route holding it

    for saving, i, j in savings_list(inst):
        if saving < -EPS:
            break
        ki, kj = owner[i], owner[j]
        if ki == kj or load[ki] + load[kj] > inst.capacity + EPS:
            continue
        a, b = routes[ki], routes[kj]
        options = []
        if a[-1] == i and b[0] == j:
            options.append(a + b)
        if b[-1] == j and a[0] == i:
            options.append(b + a)
        if a[0] == i and b[0] == j:
            options.append(a[::-1] + b)
        if a[-1] == i and b[-1] == j:
            options.append(a + b[::-1])
        for merged in options:
            if inst.route_feasible(merged):
                routes[ki] = merged
                load[ki] += load.pop(kj)
                del routes[kj]
                for node in b:
                    owner[node] = ki
                break
    return list(routes.values())
