# C101 provenance and recorded run

`c101.txt` is the complete 100-customer Solomon C101 instance, copied
verbatim from `In/c101.txt` in the [official SINTEF archive](https://www.sintef.no/globalassets/project/top/vrptw/solomon/solomon-100.zip),
retrieved 2026-09-29. `.gitattributes` disables text normalization for this
file, so its SHA256 remains the same on Windows and Linux. Its original
line-ending/padding whitespace is exempted from Git's end-of-line whitespace
check; the byte hash is enforced by the tests and demo.

| input | SHA256 |
|---|---|
| official archive | `8a0a72cbe6b7f8f9988ace4ebde0378ec34943acaaac47f2c408915e41887747` |
| `In/c101.txt` member | `a6da75152d182d60ecd2c6f854296f5be452f92282d096adebcf5d99a7f16516` |

The [SINTEF table](https://www.sintef.no/projectweb/top/vrptw/100-customers/)
lists 10 vehicles and 828.94 distance for full C101, using vehicles first
and distance second. `c101.reference.json` also records the
[published routes](https://www.sintef.no/contentassets/adf48e65e3a84dd6871eb7586707675d/c101.txt)
by Geir Hasle and Oddvar Kloster, which our independent audit confirms
feasible with total distance rounding to 828.94. This is a best-known
reference, not a proof of optimality.

The importer uses all 100 customers, without per-edge rounding. Benchmark
coordinates are numerical distance units; speed=60 embeds travel time
numerically equal to distance in the application's km/min representation.
This does not assign a real-world physical scale to the data. Depot row 0
has zero ready time, demand and service, and its due time 1236 is the shift
limit. The importer rejects other depot conventions rather than silently
discarding them. Service windows constrain the start, not end, of service.

Run from the repository root, offline and without installing packages:

```
python scripts/benchmark.py --out build/benchmark --max-moves 1000
```

The committed `results.json` and `results.csv` are one measured run.
Routes, distances and move counts are deterministic for these algorithms
and inputs; solver seed is null because there is no random restart.
Runtime and allocation peaks vary by machine/run. Timing includes
`tracemalloc` overhead and matrix construction plus solving, excluding IO,
imports and the independent audit. Memory is the peak traced Python
allocation count, not process RSS; no large-instance scaling claim follows.
Every run, including any infeasible run, remains in the report. The demo
exits 1 if any run is infeasible, after writing its violations.

Our heuristics minimize distance subject to constraints and an available
fleet. This differs from the reference's vehicles-first objective; the
record is a reference comparison, not an optimality-gap calculation.
One clustered instance does not establish general solver quality.
