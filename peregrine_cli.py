"""Peregrine compiler driver.

Usage:
  python3 peregrine_cli.py program.peregrine -o out.c          # emit C
  python3 peregrine_cli.py program.peregrine --exe prog        # emit C + cc
  python3 peregrine_cli.py program.peregrine --stats           # + analysis stats
"""

import argparse
import subprocess
import sys

from plang.backend import compile_program, PeregrineError

FLAGS = ["-O3", "-march=native", "-fopenmp-simd", "-fsimd-cost-model=unlimited",
         "-mprefer-vector-width=512", "-funroll-loops"]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="peregrine")
    ap.add_argument("source")
    ap.add_argument("-o", "--out", default=None, help="write generated C here")
    ap.add_argument("--exe", default=None, help="also compile with the C compiler")
    ap.add_argument("--cc", default="gcc")
    ap.add_argument("--O2", action="store_true", help="plain -O2 build (no SIMD flags)")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args(argv)

    src = open(args.source).read()
    try:
        code, stats = compile_program(src)
    except (PeregrineError, SyntaxError) as e:
        print(f"peregrine: error: {e}", file=sys.stderr)
        return 1

    if args.out:
        open(args.out, "w").write(code)
    elif args.exe is None:
        sys.stdout.write(code)

    if args.exe:
        cfile = args.out or (args.exe + ".c")
        if not args.out:
            open(cfile, "w").write(code)
        flags = ["-O2"] if args.O2 else FLAGS
        r = subprocess.run([args.cc] + flags + [cfile, "-o", args.exe])
        if r.returncode != 0:
            return r.returncode

    if args.stats:
        s = stats
        print(f"fields width-proven: {s['proven']}, width-checks inserted: {s['unproven']}, "
              f"bounds checks inserted: {s['checks']}, bounds checks elided by proof: {s['elided']}, "
              f"strings built in place: {s['inplace']}, loops auto-simd: {s['simd']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
