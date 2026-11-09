#!/usr/bin/env python3
"""End-to-end build time: source file -> runnable binary, per language.
Best of 3 fresh builds (output deleted each time). Measured on the map
benchmark, which pulls each ecosystem's heaviest common machinery
(unordered_map / HashMap / dictionary stdlib / map[string]uint64 /
our codegen + gcc)."""
import os
import shutil
import subprocess
import time

HERE = "/home/z/my-project/scripts/verify"
ENV = dict(os.environ)
ENV["PATH"] = "/home/z/.cargo/bin:" + ENV["PATH"]
ENV["GOOSE_HOME"] = "/home/z/my-project/.tools/goose_home"
ENV["GOCACHE"] = "/home/z/my-project/.tools/go-cache"
ENV["GOPATH"] = "/home/z/my-project/.tools/gopath"

BUILDS = [
    ("Peregrine (front+gcc -O3)",
     ["python3", "/home/z/my-project/scripts/peregrine/peregrine_cli.py",
      "map_prn.peregrine", "--exe", "/tmp/cs_prn"], ["/tmp/cs_prn", "/tmp/cs_prn.c"]),
    ("Peregrine (front end only)",
     ["python3", "/home/z/my-project/scripts/peregrine/peregrine_cli.py",
      "map_prn.peregrine", "-o", "/tmp/cs_prn.c"], ["/tmp/cs_prn.c"]),
    ("Goose (build, via gcc)",
     ["/home/z/my-project/.tools/goose-repo/goose_bin", "build",
      "map_goose.goose", "--cc", "gcc", "-o", "/tmp/cs_goose"], ["/tmp/cs_goose"]),
    ("C (gcc -O2)", ["gcc", "-O2", "map_c.c", "-o", "/tmp/cs_c"], ["/tmp/cs_c"]),
    ("C++ (g++ -O2)", ["g++", "-O2", "-std=c++20", "map_idio.cpp", "-o", "/tmp/cs_cpp"],
     ["/tmp/cs_cpp"]),
    ("Rust (rustc -O)", ["rustc", "-O", "-C", "codegen-units=1", "--edition", "2021",
                         "map_safe.rs", "-o", "/tmp/cs_rs"], ["/tmp/cs_rs"]),
    ("Go (go build)", ["/home/z/my-project/.tools/go/bin/go", "build", "-o",
                       "/tmp/cs_go", "map_go.go"], ["/tmp/cs_go"]),
]


def main():
    print(f"{'build':28s} {'best s':>8s} {'med s':>8s}")
    for label, cmd, outs in BUILDS:
        times = []
        for _ in range(3):
            for t in outs:
                if os.path.exists(t):
                    os.remove(t)
            t0 = time.monotonic()
            r = subprocess.run(cmd, cwd=HERE, env=ENV, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            t1 = time.monotonic()
            if r.returncode != 0:
                print(label, "BUILD FAILED")
                break
            times.append(t1 - t0)
        if times:
            times.sort()
            print(f"{label:28s} {times[0]:8.3f} {times[1]:8.3f}")


if __name__ == "__main__":
    main()
