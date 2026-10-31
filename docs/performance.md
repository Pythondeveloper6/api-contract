# Performance

`benchmarks/bench.py` generates OpenAPI 3.1 specs of growing size, with shared
components, nested `$ref`s, 3.1-style nullables, enums and a recursive
component, then times `normalize` and a full `diff` (both sides normalized)
against a copy with a handful of edits.

```bash
python benchmarks/bench.py                       # 100, 300 and 1000 operations
python benchmarks/bench.py --ops 2000 --repeat 5
```

Results on an Apple-silicon laptop, Python 3.12, median of 3 runs. Peak memory
is for one diff, measured in a separate run with `tracemalloc`:

| Operations | Components | normalize (s) | diff incl. normalize (s) | Peak MiB |
|---:|---:|---:|---:|---:|
| 101 | 26 | 1.6 | 4.3 | 35 |
| 301 | 76 | 2.4 | 5.1 | 104 |
| 1001 | 251 | 3.0 | 15.3 | 463 |

Loading the app (importing it and generating its schema) is not included; for
most projects that dominates.

## What keeps it bounded

- Components are inlined, so a rename of a component isn't a change. A
  component referenced more than 200 times, or nested more than 40 references
  deep, is stored once in the snapshot instead (like a recursive one), which
  keeps the snapshot and the diff from growing exponentially on heavily
  shared schemas.
- Recursive components are stored once and compared by name.

If a check is slow, run it with `-v` to see where the time goes (loading,
normalizing, diffing, reporting), and open an issue with those timings.
