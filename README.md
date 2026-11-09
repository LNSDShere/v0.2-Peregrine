# Peregrine v0.2

A small compiled systems language (~1,800 lines of auditable Python that
emit C) built around one idea: **the compiler, not the programmer, picks
the fast shape.** It tracks a provable `[lo, hi]` range for every integer
expression, stores record fields at the smallest width their values
provably occupy, segregates enum stores per variant, builds strings in
place, keys maps by inline bytes, lowers `sort()` to a radix sort, and
emits `omp simd` only on loops it has proven safe to vectorize. No garbage
collector, no heap allocator for program data, no undefined behavior —
wrapping is defined, out-of-bounds traps with the source line, and checks
are elided only by proof.

## Quickstart

```
python3 peregrine_cli.py examples/records.peregrine --exe records --stats
./records
# -> 511999968000000 329778324 1066712027060 64000000   (in ~0.6 s)
```

Requires only Python 3.10+ and a C compiler (gcc tested; `--cc` to pick
another). `--stats` prints what the compiler proved: width-proven fields,
checks inserted, bounds checks elided by proof, strings built in place,
loops auto-SIMD'd.

```
python3 peregrine_cli.py prog.peregrine -o prog.c      # just emit C
python3 peregrine_cli.py prog.peregrine --exe prog     # emit C + gcc -O3 auto-SIMD flags
python3 peregrine_cli.py prog.peregrine --exe prog --O2   # plain -O2 build
```

## What's in the box

- `peregrine_cli.py`, `plang/front.py`, `plang/backend.py` — the compiler.
  Front: lexer + recursive-descent parser. Back: range-proof analyzer and
  C code generator (stores, string plans, maps, radix sorts, SIMD gates).
- `SPEC.md` — the language: core ideas, grammar, honest limitations.
- `examples/` — `records.peregrine` (the flagship workload) and
  `safety.peregrine` (proof elision vs runtime trap, with `--stats`).
- `benchmarks/` — five workloads x seven languages (Peregrine, Goose, C,
  C++, Rust, Go, CPython), all printing bit-identical checksums, plus the
  harnesses: `build_suite.sh` (builds all 33 binaries), `run_suite.py`
  (checksum-gated timing, best-of-3 + RSS), `compile_speed.py`
  (source-to-binary time), `gen_mix.py` (generates the mix kernel for all
  seven languages from one round table).
- `RESULTS.md` — the scoreboard with Peregrine's own times, where the
  wins come from, and where Peregrine honestly loses (Goose's map,
  Rust's pdqsort on payload sorts).

Headline (2-core Xeon, gcc 14.2, N = 16M, best of 3): mix 0.215 s vs
0.64–0.77 s compiled rivals (3.0–3.6x); sort 0.351 s (3.7–6.0x over
comparison sorts); records 0.634 s (2.8–3.6x); map 1.031 s (Goose wins
at 0.642 s — documented); compile 0.151 s.

The language is v0.2: one function (`main`), match only as a store
for-in body, inline map keys (max 19 bytes), bump-only maps. See
SPEC.md for the full honest limitation list.
