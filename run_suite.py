#!/usr/bin/env python3
"""Time every implementation of every benchmark. Compiled languages: 1
warmup + 3 timed reps, best rep reported. Pure CPython: no warmup, 1 rep
(disclosed -- it is 2-3 orders of magnitude slower). Peak RSS via wait4.
Checksum equality is asserted per benchmark before timing."""
import os
import statistics
import subprocess
import sys
import time

HERE = "/home/z/my-project/scripts/verify"

# (label, argv, warmups, reps)
BENCHES = {
    "mix": [
        ("Peregrine", ["./mix_prn"], 1, 3),
        ("Goose", ["./mix_goose"], 1, 3),
        ("C natural", ["./mix_c"], 1, 3),
        ("C++ idiomatic", ["./mix_cpp_idio"], 1, 3),
        ("Rust safe", ["./mix_rust_safe"], 1, 3),
        ("Go", ["./mix_go"], 1, 3),
        ("Python", ["python3", "mix_py.py"], 0, 1),
    ],
    "sort": [
        ("Peregrine", ["./sort_prn"], 1, 3),
        ("Goose", ["./sort_goose"], 1, 3),
        ("C natural", ["./sort_c"], 1, 3),
        ("C++ idiomatic", ["./sort_cpp_idio"], 1, 3),
        ("Rust safe", ["./sort_rust_safe"], 1, 3),
        ("Go", ["./sort_go"], 1, 3),
        ("Python", ["python3", "sort_py.py"], 0, 1),
    ],
    "map": [
        ("Peregrine", ["./map_prn"], 1, 3),
        ("Goose", ["./map_goose"], 1, 3),
        ("C natural", ["./map_c"], 1, 3),
        ("C++ idiomatic", ["./map_cpp_idio"], 1, 3),
        ("Rust safe", ["./map_rust_safe"], 1, 3),
        ("Go", ["./map_go"], 1, 3),
        ("Python", ["python3", "map_py.py"], 0, 1),
    ],
    "sortrec": [
        ("Peregrine", ["./sortrec_prn"], 1, 3),
        ("Goose", ["./sortrec_goose"], 1, 3),
        ("C natural", ["./sortrec_c"], 1, 3),
        ("C++ idiomatic", ["./sortrec_cpp_idio"], 1, 3),
        ("Rust safe", ["./sortrec_rust_safe"], 1, 3),
    ],
    "records": [
        ("Peregrine", ["./records_prn"], 1, 3),
        ("Goose", ["./records_goose"], 1, 3),
        ("C++ idiomatic", ["./records_cpp_idio"], 1, 3),
        ("Rust safe", ["./records_rust_safe"], 1, 3),
        ("Go", ["./records_go"], 1, 3),
        ("Python", ["python3", "records_py.py"], 0, 1),
    ],
}


def run_once(argv):
    with open(os.devnull, "wb") as devnull:
        p = subprocess.Popen(argv, cwd=HERE, stdout=subprocess.PIPE,
                             stderr=devnull)
        t0 = time.monotonic()
        out = p.stdout.read()
        t1 = time.monotonic()
        _, status, ru = os.wait4(p.pid, 0)
        if status != 0:
            raise RuntimeError(f"{argv} exited with status {status}")
        return t1 - t0, ru.ru_maxrss / 1024.0, out.decode().strip()


def main():
    only = sys.argv[1:] or list(BENCHES)
    results = {}
    for bench in only:
        rows = []
        ref = None
        for label, argv, warm, reps in BENCHES[bench]:
            t0, rss, chk = run_once(argv)
            if ref is None:
                ref = chk
            elif chk != ref:
                print(f"CHECKSUM MISMATCH {bench}/{label}: {chk!r} != {ref!r}")
                sys.exit(1)
            times = [t0]
            for _ in range(reps):
                t, r, _ = run_once(argv)
                times.append(t)
                rss = max(rss, r)
            best = min(times)
            rows.append((label, best, statistics.median(times), rss))
            print(f"  {bench}/{label}: best={best:.3f}s rss={rss:.0f}MB", flush=True)
        results[bench] = (ref, rows)
    print()
    for bench, (ref, rows) in results.items():
        base = rows[0][1]
        print(f"{bench}  (checksum {ref[:36]})")
        print(f"{'implementation':16s} {'best s':>9s} {'med s':>8s} {'RSS MB':>8s} {'vs Peregrine':>13s}")
        for label, best, med, rss in rows:
            print(f"{label:16s} {best:9.3f} {med:8.3f} {rss:8.1f} {best / base:12.2f}x")
        print()


if __name__ == "__main__":
    main()
