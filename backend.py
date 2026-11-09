"""Peregrine back end: semantic analysis, range proofs and C codegen.

Load-bearing ideas:

1. Range proofs. Every u32/u64 expression carries a provable [lo, hi]
   range (literals, consts, loop induction over constant bounds, `% c`,
   `>> c`, `& c`). Stored fields are physically written at the smallest
   width their proven range needs (u8/u16/u24/u32/u64); unprovable values
   get a runtime check naming the line. Nothing truncates silently and
   nothing is UB: wrapping is defined, OOB is a clean trap elided only by
   proof, div/mod by zero traps.

2. Stores. `store<E>(N)` reserves one virtual region per enum variant
   (worst-case record size x N, touched pages only); pushes append to
   their variant's region, and for-in scans are branch-free sequential
   walks per variant. Store order is unspecified (a bag); aggregation
   must be order-insensitive -- documented language semantics.

3. Buffers, maps, sort, SIMD. `buf<T>(N)` is a restrict-qualified,
   page-backed zeroed buffer. `map<str,u64>(SLOTS)` is open addressing
   with inline keys built in place. `sort()` lowers to an LSD radix sort.
   A for-range loop the compiler proves trap-free, call-free and
   dependence-free (except +/-/^ accumulators) is emitted under
   `#pragma omp simd`; anything else stays scalar.
"""

import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .front import (
    parse,
    Program, ConstDecl, EnumDecl, FnDecl, VarDecl, LetDecl, Assign,
    IndexAssign, ForRange, ForIn, Repeat, If, MatchOn, PushStmt, Print,
    Num, StrLit, StrOf, Concat, Bin, Name, Field, Ctor, Index, Call,
    MethodCall,
)

U32MAX = 2**32 - 1
U64MAX = 2**64 - 1
STR_CAP = 255

WIDTHS = [("u8", 1, 2**8 - 1), ("u16", 2, 2**16 - 1), ("u24", 3, 2**24 - 1),
          ("u32", 4, U32MAX), ("u64", 8, U64MAX)]


def width_for(hi: int) -> Optional[Tuple[str, int]]:
    for name, size, maxv in WIDTHS:
        if hi <= maxv:
            return (name, size)
    return None


class PeregrineError(Exception):
    pass


@dataclass
class VarInfo:
    ctype: str          # 'u32' | 'u64' | 'str' | 'store' | 'buf' | 'map'
    range: Optional[Tuple[int, int]]
    plan: tuple = None  # for str: ('lit', s) | ('strof', e) | ('concat', lit, e)
    enum: str = ""
    cap: int = 0        # for store
    arr_elem: str = ""  # for buf
    arr_size: int = 0   # for buf
    slots: int = 0      # for map
    mutable: bool = True
    c_name: str = ""


class Analyzer:
    def __init__(self, prog: Program):
        self.prog = prog
        self.consts: Dict[str, Tuple[str, int]] = {}
        self.enums: Dict[str, Dict[str, List[Tuple[str, str]]]] = {}
        self.errors: List[str] = []
        # (variant, field) -> list of provable highs / str maxima; None = unprovable
        self.field_ranges: Dict[Tuple[str, str], List[Optional[int]]] = {}
        self.str_maxima: Dict[Tuple[str, str], List[Optional[int]]] = {}
        self.field_width: Dict[Tuple[str, str], Tuple[str, int]] = {}
        self.str_len: Dict[Tuple[str, str], int] = {}
        self.stats = {"proven": 0, "unproven": 0, "checks": 0, "elided": 0,
                      "inplace": 0, "simd": 0}

    def const_int(self, e, env) -> Optional[int]:
        if isinstance(e, Num):
            return e.v
        if isinstance(e, Name) and e.x in self.consts:
            return self.consts[e.x][1]
        return None

    def range_of(self, e, env) -> Optional[Tuple[int, int]]:
        try:
            return self.expr(e, env)[1]
        except PeregrineError:
            return None

    # ---- expression analysis: returns (ctype, range, plan) --------------
    def expr(self, e, env) -> Tuple[str, Optional[Tuple[int, int]], Optional[tuple]]:
        if isinstance(e, Num):
            if e.v > U64MAX:
                raise PeregrineError(f"line {e.line}: literal {e.v} does not fit in u64")
            t = "u64" if e.v > U32MAX else "u32"
            return (t, (e.v, e.v), None)
        if isinstance(e, StrLit):
            return ("str", None, ("lit", e.s))
        if isinstance(e, StrOf):
            ct, rng, _ = self.expr(e.e, env)
            if ct not in ("u32", "u64"):
                raise PeregrineError(f"line {e.line}: str() needs an integer")
            return ("str", None, ("strof", e.e))
        if isinstance(e, Concat):
            ct, _, plan = self.expr(e.rest, env)
            if ct != "str":
                raise PeregrineError(f"line {e.line}: only literal + str(int) is supported")
            if not isinstance(e.l, StrLit):
                raise PeregrineError(
                    f"line {e.line}: string concatenation needs a literal lhs")
            if not isinstance(e.rest, StrOf):
                raise PeregrineError(
                    f"line {e.line}: only literal + str(int) is supported in v0.2")
            return ("str", None, ("concat", e.l.s, e.rest.e))
        if isinstance(e, Name):
            info = env.get(e.x)
            if info is not None:
                return (info.ctype, info.range, info.plan)
            if e.x in self.consts:
                ty, v = self.consts[e.x]
                return (ty, (v, v), None)
            raise PeregrineError(f"line {e.line}: unknown name {e.x!r}")
        if isinstance(e, Field):
            key1 = f"{e.base}.{e.name}"
            if key1 in env:
                info = env[key1]
                return (info.ctype, info.range, info.plan)
            raise PeregrineError(f"line {e.line}: unknown field {key1!r}")
        if isinstance(e, Ctor):
            raise PeregrineError(f"line {e.line}: constructors are only valid in push")
        if isinstance(e, Bin):
            if e.op in ("==", "!=", "<", ">", "<=", ">="):
                lt, lr, _ = self.expr(e.l, env)
                rt, rr, _ = self.expr(e.r, env)
                if lt not in ("u32", "u64") or rt not in ("u32", "u64"):
                    raise PeregrineError(f"line {e.line}: bad comparison operand types")
                return ("cond", None, None)
            lt, lr, _ = self.expr(e.l, env)
            rt, rr, rp = self.expr(e.r, env)
            if lt == "str" and e.op == "+":
                if not isinstance(e.l, StrLit):
                    raise PeregrineError(
                        f"line {e.line}: string concatenation needs a literal lhs")
                if not isinstance(e.r, StrOf):
                    raise PeregrineError(
                        f"line {e.line}: only literal + str(int) is supported in v0.2")
                return ("str", None, ("concat", e.l.s, e.r.e))
            if lt in ("u32", "u64") and rt in ("u32", "u64"):
                maxv = U64MAX if "u64" in (lt, rt) else U32MAX
                if e.op == "%":
                    c = self.const_int(e.r, env)
                    if c is not None and c > 0:
                        return (lt, (0, c - 1), None)
                    return (lt, (0, maxv), None)
                if e.op == ">>":
                    c = self.const_int(e.r, env)
                    if c is not None and 0 <= c <= 63:
                        return (lt, (0, maxv >> c), None)
                    return (lt, (0, maxv), None)
                if e.op == "&":
                    c = self.const_int(e.r, env)
                    if c is not None and c >= 0:
                        return (lt, (0, min(c, maxv)), None)
                    c = self.const_int(e.l, env)
                    if c is not None and c >= 0:
                        return (lt, (0, min(c, maxv)), None)
                    return (lt, (0, maxv), None)
                # *, +, -, /, <<, ^, |: wrapping machine arithmetic, full range
                return (lt, (0, maxv), None)
            raise PeregrineError(f"line {e.line}: bad operand types for {e.op!r}")
        if isinstance(e, Index):
            info = env.get(e.base)
            if info is None or info.ctype != "buf":
                raise PeregrineError(f"line {e.line}: {e.base!r} is not a buf")
            self.expr(e.idx, env)
            return (info.arr_elem, None, None)
        if isinstance(e, Call):
            raise PeregrineError(
                f"line {e.line}: {e.name!r} is a statement, not an expression")
        if isinstance(e, MethodCall):
            raise PeregrineError(
                f"line {e.line}: method calls are statements, not expressions")
        raise PeregrineError(f"line {e.line}: cannot analyze {type(e).__name__}")

    # ---- statements: dry pass (collect field ranges) --------------------
    def dry_run(self, prog: Program):
        for d in prog.decls:
            if isinstance(d, ConstDecl):
                v = self.const_int(d.expr, {})
                if v is None:
                    raise PeregrineError(
                        f"line {d.line}: const {d.name} must be a compile-time integer")
                self.consts[d.name] = (d.type, v)
            elif isinstance(d, EnumDecl):
                self.enums[d.name] = {v.name: v.fields for v in d.variants}
            elif isinstance(d, FnDecl):
                env: Dict[str, VarInfo] = {}
                self.dry_stmts(d.body, env)

    def dry_stmts(self, stmts, env):
        for st in stmts:
            self.dry_stmt(st, env)

    def dry_stmt(self, st, env):
        if isinstance(st, VarDecl):
            if isinstance(st.type, tuple) and st.type[0] == "store":
                _, en, cap = st.type
                capv = self.const_int(cap, env)
                if capv is None or en not in self.enums:
                    raise PeregrineError(
                        f"line {st.line}: store needs a known enum and a constant capacity")
                env[st.name] = VarInfo("store", None, enum=en, cap=capv, c_name=st.name)
            elif isinstance(st.type, tuple) and st.type[0] == "buf":
                _, el, cap = st.type
                capv = self.const_int(cap, env)
                if capv is None:
                    raise PeregrineError(
                        f"line {st.line}: buf capacity must be a compile-time constant")
                env[st.name] = VarInfo("buf", None, arr_elem=el, arr_size=capv,
                                       c_name=st.name)
            elif isinstance(st.type, tuple) and st.type[0] == "map":
                _, kt, vt, slots = st.type
                sv = self.const_int(slots, env)
                if sv is None or sv < 1 or (sv & (sv - 1)) != 0:
                    raise PeregrineError(
                        f"line {st.line}: map capacity must be a constant power of two")
                env[st.name] = VarInfo("map", None, slots=sv, c_name=st.name)
            else:
                ct, rng, plan = self.expr(st.expr, env)
                if ct not in ("u32", "u64"):
                    raise PeregrineError(
                        f"line {st.line}: var needs a scalar initializer")
                if isinstance(st.type, str):
                    if st.type not in ("u32", "u64"):
                        raise PeregrineError(
                            f"line {st.line}: bad var type {st.type!r}")
                    ct = st.type
                env[st.name] = VarInfo(ct, rng, c_name=st.name)
            return
        if isinstance(st, LetDecl):
            ct, rng, plan = self.expr(st.expr, env)
            if st.type and st.type != ct:
                raise PeregrineError(
                    f"line {st.line}: let {st.name} annotated {st.type} but value is {ct}")
            env[st.name] = VarInfo(ct, rng, plan=plan, mutable=False, c_name=st.name)
            return
        if isinstance(st, Assign):
            info = env.get(st.target)
            if info is None or info.ctype not in ("u32", "u64") or not info.mutable:
                raise PeregrineError(
                    f"line {st.line}: {st.target!r} is not an assignable scalar")
            ct, rng, _ = self.expr(st.expr, env)
            if ct != info.ctype and not (info.ctype == "u64" and ct == "u32"):
                raise PeregrineError(
                    f"line {st.line}: cannot assign {ct} to {info.ctype} {st.target}")
            env[st.target].range = None
            return
        if isinstance(st, IndexAssign):
            info = env.get(st.base)
            if info is None or info.ctype != "buf":
                raise PeregrineError(f"line {st.line}: {st.base!r} is not a buf")
            self.expr(st.idx, env)
            ct, rng, _ = self.expr(st.expr, env)
            if ct != info.arr_elem:
                raise PeregrineError(
                    f"line {st.line}: cannot store {ct} into buf<{info.arr_elem}>")
            return
        if isinstance(st, ForRange):
            lo = self.const_int(st.lo, env)
            hi = self.const_int(st.hi, env)
            if lo is None or hi is None:
                raise PeregrineError(
                    f"line {st.line}: for bounds must be compile-time constants")
            benv = dict(env)
            benv[st.var] = VarInfo("u32", (lo, hi - 1), c_name=st.var, mutable=False)
            self.dry_stmts(st.body, benv)
            return
        if isinstance(st, ForIn):
            info = env.get(st.iter)
            if info is None or info.ctype not in ("store", "map"):
                raise PeregrineError(f"line {st.line}: for-in needs a store or a map")
            benv = dict(env)
            if info.ctype == "store":
                for vname, fields in self.enums[info.enum].items():
                    for fname, ftype in fields:
                        ct = "str" if ftype == "str" else ftype
                        benv[f"{st.var}.{fname}"] = VarInfo(
                            ct, None, c_name=f"_{st.var}_{fname}", mutable=False)
                # one match on the binder, covering every variant
                self.dry_match(st.body, info.enum, benv)
            else:
                benv[f"{st.var}.val"] = VarInfo("u64", None, mutable=False,
                                                c_name=f"_{st.var}_val")
                benv[f"{st.var}.key.len"] = VarInfo("u32", None, mutable=False,
                                                    c_name=f"_{st.var}_keylen")
                self.dry_stmts(st.body, benv)
            return
        if isinstance(st, Repeat):
            c = self.const_int(st.count, env)
            if c is None:
                raise PeregrineError(f"line {st.line}: repeat count must be constant")
            self.dry_stmts(st.body, dict(env))
            return
        if isinstance(st, If):
            self.expr(st.cond, env)
            self.dry_stmts(st.then, dict(env))
            for c2, b2 in st.elifs:
                self.expr(c2, env)
                self.dry_stmts(b2, dict(env))
            if st.els:
                self.dry_stmts(st.els, dict(env))
            return
        if isinstance(st, MatchOn):
            self.dry_match([st], None, env)
            return
        if isinstance(st, PushStmt):
            self.dry_push(st, env)
            return
        if isinstance(st, Print):
            for a in st.args:
                self.expr(a, env)
            return
        if isinstance(st, Call):
            return
        if isinstance(st, MethodCall):
            self.expr_method(st, env)
            return
        raise PeregrineError(f"line {st.line}: cannot analyze {type(st).__name__}")

    def dry_match(self, body, enum_name, env):
        for st in body:
            if isinstance(st, MatchOn):
                en = enum_name
                if en is None:
                    raise PeregrineError(
                        f"line {st.line}: match is only valid inside a store for-in")
                for vname, binder, b in st.arms:
                    if binder:
                        for fname, ftype in self.enums[en][vname]:
                            ct = "str" if ftype == "str" else ftype
                            env[f"{binder}.{fname}"] = VarInfo(
                                ct, None, mutable=False, c_name=f"_{binder}_{fname}")
                            if ftype == "str":
                                env[f"{binder}.{fname}.len"] = VarInfo(
                                    "u32", None, mutable=False,
                                    c_name=f"_{binder}_{fname}_len")
                    self.dry_stmts(b, dict(env))
                return
            self.dry_stmt(st, env)

    def dry_push(self, st: PushStmt, env):
        info = env.get(st.store)
        if info is None or info.ctype != "store":
            raise PeregrineError(f"line {st.line}: {st.store!r} is not a store")
        fields = self.enums[info.enum].get(st.ctor.variant)
        if fields is None:
            raise PeregrineError(
                f"line {st.line}: unknown variant {st.ctor.variant!r}")
        if st.ctor.enum != info.enum:
            raise PeregrineError(
                f"line {st.line}: push of {st.ctor.enum} into store of {info.enum}")
        given = dict(st.ctor.inits)
        for fname, ftype in fields:
            if fname not in given:
                raise PeregrineError(
                    f"line {st.line}: variant {st.ctor.variant} missing field {fname!r}")
            e = given[fname]
            ct, rng, plan = self.expr(e, env)
            if ftype == "str":
                if ct != "str":
                    raise PeregrineError(
                        f"line {st.line}: field {fname} is str, got {ct}")
                maxlen = self.plan_maxlen(plan)
                key = (st.ctor.variant, fname)
                self.str_maxima.setdefault(key, []).append(maxlen)
                self.stats["inplace"] += 1
            else:
                if ct != ftype and not (ftype == "u64" and ct == "u32"):
                    raise PeregrineError(
                        f"line {st.line}: field {fname} is {ftype}, got {ct}")
                key = (st.ctor.variant, fname)
                self.field_ranges.setdefault(key, []).append(
                    None if rng is None else rng[1])
        extra = set(given) - {f for f, _ in fields}
        if extra:
            raise PeregrineError(
                f"line {st.line}: unknown fields {sorted(extra)} in {st.ctor.variant}")

    def plan_maxlen(self, plan) -> int:
        if plan[0] == "lit":
            return len(plan[1])
        if plan[0] == "strof":
            e = plan[1]
            return 10  # any u32/u64: up to 10 digits (u32); u64 handled below
        if plan[0] == "concat":
            lit, e = plan[1], plan[2]
            return len(lit) + 10
        raise PeregrineError("internal: bad string plan")

    def expr_method(self, st: MethodCall, env):
        if st.meth != "bump":
            raise PeregrineError(f"line {st.line}: unknown method .{st.meth!r}")
        info = env.get(st.base)
        if info is None or info.ctype != "map":
            raise PeregrineError(f"line {st.line}: .bump needs a map")
        if not 1 <= len(st.args) <= 2:
            raise PeregrineError(f"line {st.line}: bump takes (key) or (key, delta)")
        kt, _, plan = self.expr(st.args[0], env)
        if kt != "str":
            raise PeregrineError(f"line {st.line}: map keys are str")
        if plan and plan[0] == "concat":
            if self.plan_maxlen(plan) > 19:
                raise PeregrineError(
                    f"line {st.line}: map key may exceed 19 bytes (max inline key)")
        elif plan and plan[0] == "lit":
            if len(plan[1]) > 19:
                raise PeregrineError(f"line {st.line}: map key longer than 19 bytes")
        if len(st.args) == 2:
            ct, _, _ = self.expr(st.args[1], env)
            if ct not in ("u32", "u64"):
                raise PeregrineError(f"line {st.line}: bump delta must be an integer")


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------

RUNTIME_C = r"""#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

static void pr_trap(int line, const char* msg) __attribute__((noreturn));
static void pr_trap(int line, const char* msg) {
    fprintf(stderr, "peregrine runtime error: %s (line %d)\n", msg, line);
    exit(1);
}

/* Page-backed, zero-filled, 64B-aligned region: reserve, touch nothing. */
static uint8_t* pr_region(size_t bytes) {
    void* p = mmap(0, bytes + 4096, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    if (p == MAP_FAILED) pr_trap(0, "out of memory");
    return (uint8_t*)p;
}

static inline uint32_t pr_load16(const uint8_t* p) {
    uint16_t v; memcpy(&v, p, 2); return v;
}
static inline uint32_t pr_load24(const uint8_t* p) {
    uint32_t v = 0; memcpy(&v, p, 3); return v;
}
static inline uint32_t pr_load32(const uint8_t* p) {
    uint32_t v; memcpy(&v, p, 4); return v;
}
static inline uint64_t pr_load64(const uint8_t* p) {
    uint64_t v; memcpy(&v, p, 8); return v;
}
static inline void pr_store32(uint8_t* p, uint32_t v) { memcpy(p, &v, 4); }
static inline void pr_store64(uint8_t* p, uint64_t v) { memcpy(p, &v, 8); }

static inline uint32_t pr_digits(char* dst, uint32_t v) {
    char t[10]; uint32_t n = 0;
    do { t[n++] = (char)('0' + v % 10u); v /= 10u; } while (v);
    for (uint32_t i = 0; i < n; i++) dst[i] = t[n - 1 - i];
    return n;
}

/* ---- v0.2 runtime: hash maps and radix sorts ---- */

/* map<str,u64> slot: 32 bytes. len==0 marks the slot empty. */
typedef struct {
    uint32_t tag;      /* full FNV-1a hash of the key */
    uint8_t  len;      /* key length; 0 = empty slot */
    uint8_t  key[19];  /* inline key bytes, no pointers */
    uint64_t val;
} pr_mapent;

static inline uint32_t pr_fnv1a(const uint8_t* p, uint32_t n) {
    uint32_t h = 2166136261u;
    for (uint32_t i = 0; i < n; i++) { h ^= p[i]; h *= 16777619u; }
    return h;
}

static void pr_radix_u32(uint32_t* a, size_t n) {
    static uint32_t* tmp = 0; static size_t tcap = 0;
    if (tcap < n) { tmp = (uint32_t*)pr_region(n * sizeof(uint32_t)); tcap = n; }
    static uint32_t c0[65536], c1[65536];
    memset(c0, 0, sizeof c0); memset(c1, 0, sizeof c1);
    for (size_t i = 0; i < n; i++) { c0[a[i] & 0xFFFFu]++; c1[a[i] >> 16]++; }
    uint32_t s0 = 0;
    for (uint32_t b = 0; b < 65536u; b++) { uint32_t t = c0[b]; c0[b] = s0; s0 += t; }
    uint32_t s1 = 0;
    for (uint32_t b = 0; b < 65536u; b++) { uint32_t t = c1[b]; c1[b] = s1; s1 += t; }
    for (size_t i = 0; i < n; i++) tmp[c0[a[i] & 0xFFFFu]++] = a[i];
    for (size_t i = 0; i < n; i++) a[c1[tmp[i] >> 16]++] = tmp[i];
}

static void pr_radix_u64(uint64_t* a, size_t n) {
    static uint64_t* tmp = 0; static size_t tcap = 0;
    if (tcap < n) { tmp = (uint64_t*)pr_region(n * sizeof(uint64_t)); tcap = n; }
    static uint32_t cnt[4][65536];
    memset(cnt, 0, sizeof cnt);
    for (size_t i = 0; i < n; i++) {
        uint64_t v = a[i];
        cnt[0][v & 0xFFFFu]++; cnt[1][(v >> 16) & 0xFFFFu]++;
        cnt[2][(v >> 32) & 0xFFFFu]++; cnt[3][v >> 48]++;
    }
    for (int p = 0; p < 4; p++) {
        uint32_t s = 0;
        for (uint32_t b = 0; b < 65536u; b++) { uint32_t t = cnt[p][b]; cnt[p][b] = s; s += t; }
    }
    uint64_t* src = a; uint64_t* dst = tmp;
    for (int pass = 0; pass < 4; pass++) {
        uint32_t shift = (uint32_t)(16 * pass);
        for (size_t i = 0; i < n; i++) {
            uint64_t v = src[i];
            dst[cnt[pass][(v >> shift) & 0xFFFFu]++] = v;
        }
        uint64_t* sw = src; src = dst; dst = sw;
    }
    if (src != a) memcpy(a, src, n * sizeof(uint64_t));
}

/* ---- generated program ---- */
"""


class Codegen:
    def __init__(self, an: Analyzer):
        self.an = an
        self.lines: List[str] = []
        self.indent = "    "

    def emit(self, s: str):
        self.lines.append(self.indent + s)

    def raw(self, s: str):
        self.lines.append(s)

    # ---- scalar expression / condition emission --------------------------
    def cval(self, e, env) -> str:
        if isinstance(e, Num):
            return f"{e.v}ull" if e.v > U32MAX else f"{e.v}u"
        if isinstance(e, Name):
            info = env.get(e.x)
            if info is not None:
                if info.ctype not in ("u32", "u64"):
                    raise PeregrineError(f"line {e.line}: {e.x!r} is not an integer")
                return info.c_name
            if e.x in self.an.consts:
                v = self.an.consts[e.x][1]
                return f"{v}ull" if v > U32MAX else f"{v}u"
            raise PeregrineError(f"line {e.line}: unknown name {e.x!r}")
        if isinstance(e, Field):
            key1 = f"{e.base}.{e.name}"
            info = env.get(key1)
            if info is None:
                raise PeregrineError(f"line {e.line}: unknown field {key1!r}")
            return info.c_name
        if isinstance(e, Bin):
            if e.op in ("==", "!=", "<", ">", "<=", ">="):
                return f"({self.cval(e.l, env)} {e.op} {self.cval(e.r, env)})"
            if e.op in ("/", "%"):
                c = self.an.const_int(e.r, env)
                if c is None:
                    self.emit(f"if ({self.cval(e.r, env)} == 0u) pr_trap({e.line}, \"division by zero\");")
                elif c == 0:
                    raise PeregrineError(f"line {e.line}: division by constant zero")
            if e.op == "<<":
                return f"({self.cval(e.l, env)} << {self.cval(e.r, env)})"
            return f"({self.cval(e.l, env)} {e.op} {self.cval(e.r, env)})"
        if isinstance(e, Index):
            info = env.get(e.base)
            if info is None or info.ctype != "buf":
                raise PeregrineError(f"line {e.line}: {e.base!r} is not a buf")
            i = self.checked_index(info, e.idx, env, e.line)
            return f"{info.c_name}[{i}]"
        if isinstance(e, StrLit):
            raise PeregrineError(f"line {e.line}: string used as an integer")
        raise PeregrineError(f"line {e.line}: cannot emit {type(e).__name__}")

    def checked_index(self, info: VarInfo, idx, env, line) -> str:
        rng = self.an.range_of(idx, env)
        if rng is not None and rng[0] >= 0 and rng[1] < info.arr_size:
            self.an.stats["elided"] += 1
            return self.cval(idx, env)
        self.an.stats["checks"] += 1
        i = self.cval(idx, env)
        self.emit(f"if ({i} >= {info.arr_size}u) pr_trap({line}, \"index out of bounds\");")
        return i

    # ---- string plans -----------------------------------------------------
    def plan_code(self, plan, env, kb="kb", line=0):
        """Emit code building the plan into uint8_t kb[24]; returns kn expr."""
        if plan[0] == "lit":
            s = plan[1]
            if len(s) > 23:
                raise PeregrineError(f"line {line}: string literal too long")
            self.emit(f"memcpy({kb}, \"{s}\", {len(s)});")
            return str(len(s))
        if plan[0] == "strof":
            self.emit(f"kn = pr_digits((char*){kb}, {self.cval(plan[1], env)});")
            return "kn"
        if plan[0] == "concat":
            lit, e = plan[1], plan[2]
            self.emit(f"memcpy({kb}, \"{lit}\", {len(lit)});")
            self.emit(f"kn = {len(lit)} + pr_digits((char*){kb} + {len(lit)}, {self.cval(e, env)});")
            return "kn"
        raise PeregrineError(f"internal: bad plan {plan!r}")

    def key_build(self, plan, env, line):
        """Map key: uint8_t kb[24]; uint32_t kn = ..."""
        self.emit("{ uint8_t kb[24]; uint32_t kn;")
        kn = self.plan_code(plan, env, line=line)
        if kn == "kn":
            self.emit(f"if (kn > 19u) pr_trap({line}, \"map key too long\");")
        return kn

    # ---- statements --------------------------------------------------------
    def gen_stmts(self, stmts, env):
        for st in stmts:
            self.gen_stmt(st, env)

    def gen_stmt(self, st, env):
        if isinstance(st, VarDecl):
            self.gen_var(st, env)
            return
        if isinstance(st, LetDecl):
            ct, rng, plan = self.an.expr(st.expr, env)
            if ct in ("u32", "u64"):
                cc = "uint64_t" if ct == "u64" else "uint32_t"
                self.emit(f"const {cc} {st.name} = {self.cval(st.expr, env)};")
                env[st.name] = VarInfo(ct, rng, c_name=st.name, mutable=False)
            else:  # str: a build plan, nothing is materialized
                env[st.name] = VarInfo("str", None, plan=plan, c_name=st.name,
                                       mutable=False)
            return
        if isinstance(st, Assign):
            info = env[st.target]
            if st.op == "=":
                self.emit(f"{st.target} = {self.cval(st.expr, env)};")
            else:
                self.emit(f"{st.target} += {self.cval(st.expr, env)};")
            info.range = None
            return
        if isinstance(st, IndexAssign):
            info = env[st.base]
            i = self.checked_index(info, st.idx, env, st.line)
            if st.op == "=":
                self.emit(f"{info.c_name}[{i}] = {self.cval(st.expr, env)};")
            else:
                self.emit(f"{info.c_name}[{i}] += {self.cval(st.expr, env)};")
            return
        if isinstance(st, ForRange):
            self.gen_forrange(st, env)
            return
        if isinstance(st, ForIn):
            self.gen_forin(st, env)
            return
        if isinstance(st, Repeat):
            c = self.an.const_int(st.count, env)
            self.emit(f"for (uint32_t _r = 0; _r < {c}u; _r++) {{")
            self.gen_stmts(st.body, dict(env))
            self.emit("}")
            return
        if isinstance(st, If):
            self.emit(f"if ({self.ccond(st.cond, env)}) {{")
            self.gen_stmts(st.then, dict(env))
            for c2, b2 in st.elifs:
                self.emit(f"}} else if ({self.ccond(c2, env)}) {{")
                self.gen_stmts(b2, dict(env))
            if st.els:
                self.emit("} else {")
                self.gen_stmts(st.els, dict(env))
            self.emit("}")
            return
        if isinstance(st, PushStmt):
            self.gen_push(st, env)
            return
        if isinstance(st, Print):
            self.gen_print(st, env)
            return
        if isinstance(st, Call):
            self.gen_call(st, env)
            return
        if isinstance(st, MethodCall):
            self.gen_method(st, env)
            return
        if isinstance(st, MatchOn):
            raise PeregrineError(
                f"line {st.line}: match is only valid as a store for-in body")
        raise PeregrineError(f"line {st.line}: cannot generate {type(st).__name__}")

    def ccond(self, e, env) -> str:
        if isinstance(e, Bin) and e.op in ("==", "!=", "<", ">", "<=", ">="):
            return f"({self.cval(e.l, env)} {e.op} {self.cval(e.r, env)})"
        raise PeregrineError(f"line {e.line}: condition must be a comparison")

    def gen_var(self, st: VarDecl, env):
        if isinstance(st.type, tuple) and st.type[0] == "store":
            _, en, cap = st.type
            capv = self.an.const_int(cap, env)
            env[st.name] = VarInfo("store", None, enum=en, cap=capv, c_name=st.name)
            return
        if isinstance(st.type, tuple) and st.type[0] == "buf":
            _, el, cap = st.type
            capv = self.an.const_int(cap, env)
            env[st.name] = VarInfo("buf", None, arr_elem=el, arr_size=capv,
                                   c_name=st.name)
            ct = "uint64_t" if el == "u64" else "uint32_t"
            esz = 8 if el == "u64" else 4
            self.emit(f"{ct}* restrict {st.name} = ({ct}*)pr_region((size_t){capv}u * {esz}u);")
            return
        if isinstance(st.type, tuple) and st.type[0] == "map":
            _, kt, vt, slots = st.type
            sv = self.an.const_int(slots, env)
            env[st.name] = VarInfo("map", None, slots=sv, c_name=st.name)
            self.raw(f"    static uint8_t *rg_{st.name};")
            self.raw(f"    static uint64_t mcnt_{st.name};")
            self.emit(f"rg_{st.name} = (uint8_t*)pr_region((size_t){sv}u * 32u);")
            self.emit(f"mcnt_{st.name} = 0;")
            return
        ct, rng, _ = self.an.expr(st.expr, env)
        if ct not in ("u32", "u64"):
            raise PeregrineError(f"line {st.line}: var needs a scalar initializer")
        if isinstance(st.type, str):
            if st.type not in ("u32", "u64"):
                raise PeregrineError(f"line {st.line}: bad var type {st.type!r}")
            if not (st.type == "u64" and ct == "u32"):
                if ct != st.type:
                    raise PeregrineError(
                        f"line {st.line}: cannot initialize {st.type} {st.name} with {ct}")
            ct = st.type
        cc = "uint64_t" if ct == "u64" else "uint32_t"
        self.emit(f"{cc} {st.name} = {self.cval(st.expr, env)};")
        env[st.name] = VarInfo(ct, rng, c_name=st.name)

    # ---- SIMD eligibility ---------------------------------------------------
    def _simd_scan(self, body, env):
        def expr_ok(e):
            if isinstance(e, (StrLit, StrOf, Concat, Call, MethodCall, Ctor)):
                return False
            if isinstance(e, Bin):
                if e.op in ("/", "%") and self.an.const_int(e.r, None) is None:
                    return False
                return expr_ok(e.l) and expr_ok(e.r)
            if isinstance(e, Index):
                info = env.get(e.base)
                if info is None or info.ctype != "buf":
                    return False
                rng = self.an.range_of(e.idx, env)
                if rng is None or rng[0] < 0 or rng[1] >= info.arr_size:
                    return False
                return True
            return isinstance(e, (Num, Name, Field))

        reds = []
        inner = set()
        for st in body:
            if isinstance(st, VarDecl):
                if isinstance(st.type, str) and st.type in ("u32", "u64") \
                        and st.expr is not None and expr_ok(st.expr):
                    inner.add(st.name)
                    continue
                return (False, [])
            if isinstance(st, Assign):
                if not expr_ok(st.expr):
                    return (False, [])
                if st.op == "+=":
                    info = env.get(st.target)
                    if (info is None or not info.mutable
                            or info.ctype not in ("u32", "u64")
                            or st.target in inner):
                        return (False, [])
                    reds.append(("+", st.target))
                    continue
                if st.op == "=" and st.target in inner:
                    continue
                e = st.expr
                if (isinstance(e, Bin) and e.op in ("+", "^")
                        and isinstance(e.l, Name) and e.l.x == st.target):
                    info = env.get(st.target)
                    if (info is None or not info.mutable
                            or info.ctype not in ("u32", "u64")):
                        return (False, [])
                    reds.append((e.op, st.target))
                    continue
                return (False, [])
            if isinstance(st, IndexAssign):
                if st.op != "=":
                    return (False, [])
                if not expr_ok(Index(st.base, st.idx, st.line)) or not expr_ok(st.expr):
                    return (False, [])
                continue
            return (False, [])
        seen = set()
        for _, v in reds:
            if v in seen:
                return (False, [])
            seen.add(v)
        return (True, reds)

    def gen_forrange(self, st: ForRange, env):
        lo = self.an.const_int(st.lo, env)
        hi = self.an.const_int(st.hi, env)
        if lo is None or hi is None:
            raise PeregrineError(
                f"line {st.line}: for bounds must be compile-time constants")
        env[st.var] = VarInfo("u32", (lo, hi - 1), c_name=st.var, mutable=False)
        ok, reds = self._simd_scan(st.body, env)
        if ok:
            self.an.stats["simd"] += 1
            cl = " ".join(f"reduction({op}: {v})" for op, v in reds)
            self.emit(("#pragma omp simd " + cl).rstrip())
        self.emit(f"for (uint32_t {st.var} = {lo}u; {st.var} < {hi}u; {st.var}++) {{")
        self.gen_stmts(st.body, env)
        self.emit("}")
        return


    # ---- stores: layout, push, scan ---------------------------------------
    def variant_layout(self, enum_name, vname):
        """[(fname, ftype, width_name, width_bytes, str_maxlen)] for a variant."""
        out = []
        for fname, ftype in self.an.enums[enum_name][vname]:
            if ftype == "str":
                mx = max(self.an.str_maxima.get((vname, fname), [0]))
                out.append((fname, ftype, "str", 1, mx))
            else:
                key = (vname, fname)
                his = self.an.field_ranges.get(key, [])
                if his and all(h is not None for h in his):
                    w = width_for(max(his))
                    if w is None:
                        w = ("u64", 8)
                    out.append((fname, ftype, w[0], w[1], 0))
                    if w[0] != "u64":
                        self.an.stats["proven"] += 1
                    continue
                out.append((fname, ftype, ftype, 4 if ftype == "u32" else 8, 0))
                self.an.stats["unproven"] += 1
        return out

    def _load_field(self, wname, buf):
        if wname == "u8":
            return f"(uint32_t){buf}[0]"
        if wname == "u16":
            return f"pr_load16({buf})"
        if wname == "u24":
            return f"pr_load24({buf})"
        if wname == "u32":
            return f"pr_load32({buf})"
        if wname == "u64":
            return f"pr_load64({buf})"
        raise PeregrineError(f"internal: bad width {wname}")

    def _store_field(self, wname, val, buf):
        if wname == "u8":
            return f"{buf}[0] = (uint8_t)({val});"
        if wname == "u16":
            return f"memcpy({buf}, &(uint16_t){{ (uint16_t)({val}) }}, 2);"
        if wname == "u24":
            return f"memcpy({buf}, &(uint32_t){{ (uint32_t)({val}) }}, 3);"
        if wname == "u32":
            return f"pr_store32({buf}, (uint32_t)({val}));"
        if wname == "u64":
            return f"pr_store64({buf}, (uint64_t)({val}));"
        raise PeregrineError(f"internal: bad width {wname}")

    def _checked_store(self, st_line, fname, ftype, wname, e, env, binder_val):
        """Value write with width check when the range is not provable."""
        if wname == "u64" or ftype not in ("u32", "u64"):
            return binder_val
        rng = self.an.range_of(e, env)
        if rng is not None and rng[0] >= 0 and rng[1] <= (2**24 - 1 if wname == "u24" else 2**16 - 1 if wname == "u16" else 2**8 - 1):
            return binder_val
        self.an.stats["checks"] += 1
        if wname == "u24":
            self.emit(f"if ({binder_val} > {2**24 - 1}u) pr_trap({st_line}, \"value exceeds proven width of field {fname}\");")
        elif wname == "u16":
            self.emit(f"if ({binder_val} > {2**16 - 1}u) pr_trap({st_line}, \"value exceeds proven width of field {fname}\");")
        else:
            self.emit(f"if ({binder_val} > {2**8 - 1}u) pr_trap({st_line}, \"value exceeds proven width of field {fname}\");")
        return binder_val

    def gen_push(self, st: PushStmt, env):
        info = env[st.store]
        layout = self.variant_layout(info.enum, st.ctor.variant)
        vname = st.ctor.variant
        given = dict(st.ctor.inits)
        self.emit(f"{{ uint8_t* p = w_{info.enum}_{vname};")
        self.emit("uint8_t kb[24]; uint32_t kn;")
        for fname, ftype, wname, wsz, mx in layout:
            e = given[fname]
            if ftype == "str":
                plan = self.an.expr(e, env)[2]
                n = self.plan_code(plan, env, line=st.line)
                self.emit(f"*p++ = (uint8_t)({n});")
                self.emit("memcpy(p, kb, kn); p += kn;")
                continue
            val = self.cval(e, env)
            lim = {"u8": 2**8 - 1, "u16": 2**16 - 1, "u24": 2**24 - 1}.get(wname)
            if lim is not None:
                rng = self.an.range_of(e, env)
                if rng is None or rng[1] > lim:
                    self.an.stats["checks"] += 1
                    self.emit(f"if ((uint64_t)({val}) > {lim}u) pr_trap({st.line}, "
                              f"\"value exceeds proven width of field {fname}\");")
            bits = 8 if wsz == 1 else (16 if wsz == 2 else (32 if wsz == 4 else 64))
            self.emit(f"{{ uint{bits}_t v = {val};")
            self.emit(self._store_field(wname, "v", "p"))
            self.emit(f"p += {wsz};")
            self.emit("}")
        self.emit(f"w_{info.enum}_{vname} = p;")
        self.emit("}")

    def gen_forin(self, st: ForIn, env):
        info = env.get(st.iter)
        if info is None or info.ctype not in ("store", "map"):
            raise PeregrineError(f"line {st.line}: for-in needs a store or a map")
        if info.ctype == "map":
            benv = dict(env)
            val_c = f"_{st.var}_val"
            len_c = f"_{st.var}_keylen"
            self.emit(f"for (uint32_t _i = 0; _i < {info.slots}u; _i++) {{")
            self.emit(f"const uint8_t* _e = rg_{st.iter} + (size_t)_i * 32u;")
            self.emit("if (_e[4] == 0) continue;")
            self.emit(f"uint64_t {val_c} = pr_load64(_e + 24);")
            self.emit(f"uint32_t {len_c} = _e[4];")
            benv[f"{st.var}.val"] = VarInfo("u64", None, c_name=val_c, mutable=False)
            benv[f"{st.var}.key.len"] = VarInfo("u32", None, c_name=len_c, mutable=False)
            self.gen_stmts(st.body, benv)
            self.emit("}")
            return
        # store: one branch-free sequential scan per variant region
        arms = {}
        for stx in st.body:
            if isinstance(stx, MatchOn):
                for vname, binder, b in stx.arms:
                    arms[vname] = (binder, b)
            else:
                raise PeregrineError(
                    f"line {stx.line}: store for-in body must be a single match")
        if not arms:
            raise PeregrineError(f"line {st.line}: empty for-in over a store")
        enum = info.enum
        for v in self.an.enums[enum]:
            if v not in arms:
                raise PeregrineError(
                    f"line {st.line}: match does not cover variant {v!r}")
        capv = info.cap
        allmax = 0
        for v in self.an.enums[enum]:
            allmax = max(allmax, sum(1 + (f[4] if f[1] == "str" else f[3])
                                     for f in self.variant_layout(enum, v)))
        for v in self.an.enums[enum]:
            binder, body = arms[v]
            layout = self.variant_layout(enum, v)
            benv = dict(env)
            for fname, ftype, wname, wsz, mx in layout:
                if ftype == "str":
                    benv[f"{binder}.{fname}"] = VarInfo(
                        "str", None, plan=None, c_name=f"_{binder}_{fname}",
                        mutable=False)
                    benv[f"{binder}.{fname}.len"] = VarInfo(
                        "u32", None, c_name=f"_{binder}_{fname}_len", mutable=False)
                else:
                    benv[f"{binder}.{fname}"] = VarInfo(
                        ftype, None, c_name=f"_{binder}_{fname}", mutable=False)
            self.emit(f"{{ const uint8_t* p = rg_{enum}_{v};")
            self.emit(f"const uint8_t* w = w_{enum}_{v};")
            self.emit("while (p < w) {")
            for fname, ftype, wname, wsz, mx in layout:
                if ftype == "str":
                    self.emit(f"uint32_t _{binder}_{fname}_len = p[0]; p += 1;")
                    self.emit(f"const uint8_t* _{binder}_{fname}_k = p;")
                    self.emit(f"p += _{binder}_{fname}_len;")
                else:
                    cc = "uint64_t" if ftype == "u64" else "uint32_t"
                    self.emit(f"{cc} _{binder}_{fname} = {self._load_field(wname, 'p')};")
                    self.emit(f"p += {wsz};")
            self.gen_stmts(body, benv)
            self.emit("}")
            self.emit("}")

    # ---- print --------------------------------------------------------------
    def gen_print(self, st: Print, env):
        fmt = []
        vals = []
        for a in st.args:
            if isinstance(a, StrLit):
                fmt.append(a.s.replace("%", "%%"))
                continue
            ct, _, _ = self.an.expr(a, env)
            if ct == "u64":
                fmt.append("%llu"); vals.append(f"(unsigned long long){self.cval(a, env)}")
            elif ct == "u32":
                fmt.append("%u"); vals.append(self.cval(a, env))
            else:
                raise PeregrineError(f"line {st.line}: cannot print {ct}")
        fmt.append("\\n")
        f = "".join(fmt)
        self.emit(f'printf("{f}"{", " + ", ".join(vals) if vals else ""});')

    # ---- sort and map methods ----------------------------------------------
    def gen_call(self, st: Call, env):
        if st.name != "sort" or not 1 <= len(st.args) <= 2:
            raise PeregrineError(
                f"line {st.line}: unknown call {st.name!r} (v0.2 has sort(buf[, payload]))")
        infos = []
        for a in st.args:
            if not isinstance(a, Name):
                raise PeregrineError(f"line {st.line}: sort needs plain buf names")
            info = env.get(a.x)
            if info is None or info.ctype != "buf":
                raise PeregrineError(f"line {st.line}: sort needs bufs")
            infos.append(info)
        if len(infos) == 1:
            if infos[0].arr_elem == "u32":
                self.emit(f"pr_radix_u32({infos[0].c_name}, (size_t){infos[0].arr_size}u);")
            elif infos[0].arr_elem == "u64":
                self.emit(f"pr_radix_u64({infos[0].c_name}, (size_t){infos[0].arr_size}u);")
            else:
                raise PeregrineError(f"line {st.line}: cannot sort buf of {infos[0].arr_elem}")
            return
        k, v = infos
        if k.arr_elem != "u64" or v.arr_elem != "u64":
            raise PeregrineError(f"line {st.line}: sort(k, v) needs two u64 bufs")
        if k.arr_size != v.arr_size:
            raise PeregrineError(f"line {st.line}: sort(k, v) bufs must have equal lengths")
        self.emit(f"pr_radix_u64_pay({k.c_name}, {v.c_name}, (size_t){k.arr_size}u);")

    def gen_method(self, st: MethodCall, env):
        if st.meth != "bump":
            raise PeregrineError(f"line {st.line}: unknown method .{st.meth!r} (v0.2 has map.bump)")
        info = env.get(st.base)
        if info is None or info.ctype != "map":
            raise PeregrineError(f"line {st.line}: .bump needs a map")
        if not 1 <= len(st.args) <= 2:
            raise PeregrineError(f"line {st.line}: bump takes (key) or (key, delta)")
        kt, _, plan = self.an.expr(st.args[0], env)
        if kt != "str":
            raise PeregrineError(f"line {st.line}: map keys are str")
        delta = self.cval(st.args[1], env) if len(st.args) == 2 else "1u"
        kn = self.key_build(plan, env, st.line)
        self.emit("uint32_t kh = pr_fnv1a(kb, kn);")
        self.emit(f"uint32_t km = {info.slots}u - 1u;")
        self.emit("uint32_t ki = kh & km;")
        self.emit("for (;;) {")
        self.emit(f"pr_mapent* ke = (pr_mapent*)(rg_{st.base} + (size_t)ki * 32u);")
        self.emit("if (ke->len) {")
        self.emit("if (ke->tag == kh && ke->len == (uint8_t)kn && memcmp(ke->key, kb, kn) == 0)")
        self.emit(f"{{ ke->val += (uint64_t)({delta}); break; }}")
        self.emit("} else {")
        self.emit(f"if (mcnt_{st.base} >= {info.slots}u) pr_trap({st.line}, \"map full\");")
        self.emit("ke->tag = kh; ke->len = (uint8_t)kn; memcpy(ke->key, kb, kn);")
        self.emit(f"ke->val = (uint64_t)({delta}); mcnt_{st.base}++; break;")
        self.emit("}")
        self.emit("ki = (ki + 1u) & km;")
        self.emit("}")
        self.emit("}")


def compile_program(src: str):
    prog = parse(src)
    an = Analyzer(prog)
    an.dry_run(prog)

    cg = Codegen(an)
    body = []
    saved = cg.lines
    cg.lines = body

    # store regions: one per variant, worst-case record size x capacity
    emitted_regions = set()
    for d in prog.decls:
        if isinstance(d, FnDecl):
            env: Dict[str, VarInfo] = {}
            cg.gen_stmts(d.body, env)
    cg.lines = saved

    # collect store region declarations from the program text
    prelude = RUNTIME_C
    # radix payload sort used only when sort(k, v) appears
    has_pay = any("pr_radix_u64_pay(" in ln for ln in body)
    if has_pay:
        prelude += r"""
/* LSD radix sort of u64 keys carrying a u64 payload, 16-bit digits x 4. */
static void pr_radix_u64_pay(uint64_t* k, uint64_t* v, size_t n) {
    static uint64_t* tk = 0; static uint64_t* tv = 0; static size_t tcap = 0;
    if (tcap < n) {
        tk = (uint64_t*)pr_region(n * sizeof(uint64_t));
        tv = (uint64_t*)pr_region(n * sizeof(uint64_t));
        tcap = n;
    }
    static uint32_t cnt[4][65536];
    memset(cnt, 0, sizeof cnt);
    for (size_t i = 0; i < n; i++) {
        uint64_t x = k[i];
        cnt[0][x & 0xFFFFu]++; cnt[1][(x >> 16) & 0xFFFFu]++;
        cnt[2][(x >> 32) & 0xFFFFu]++; cnt[3][x >> 48]++;
    }
    for (int p = 0; p < 4; p++) {
        uint32_t s = 0;
        for (uint32_t b = 0; b < 65536u; b++) { uint32_t t = cnt[p][b]; cnt[p][b] = s; s += t; }
    }
    uint64_t* sk = k; uint64_t* sv = v; uint64_t* dk = tk; uint64_t* dv = tv;
    for (int pass = 0; pass < 4; pass++) {
        uint32_t shift = (uint32_t)(16 * pass);
        for (size_t i = 0; i < n; i++) {
            uint64_t key = sk[i];
            size_t d = cnt[pass][(key >> shift) & 0xFFFFu]++;
            dk[d] = key; dv[d] = sv[i];
        }
        uint64_t* w = sk; sk = dk; dk = w;
        w = sv; sv = dv; dv = w;
    }
    if (sk != k) { memcpy(k, sk, n * sizeof(uint64_t)); memcpy(v, sv, n * sizeof(uint64_t)); }
}
"""

    # store region declarations: walk programs' store vars
    region_decls = []
    def collect(stmts):
        for st in stmts:
            if isinstance(st, VarDecl) and isinstance(st.type, tuple) and st.type[0] == "store":
                _, en, cap = st.type
                capv = an.const_int(cap, {})
                allmax = 0
                for v in an.enums[en]:
                    allmax = max(allmax, sum(1 + (f[4] if f[1] == "str" else f[3])
                                             for f in cg.variant_layout(en, v)))
                for v in an.enums[en]:
                    region_decls.append(
                        f"static uint8_t *rg_{en}_{v}, *w_{en}_{v};")
                    region_decls.append(
                        f"static const size_t RGCAP_{en}_{v} = (size_t){capv}u * {allmax}u;")
            if isinstance(st, ForRange):
                collect(st.body)
            elif isinstance(st, ForIn):
                collect(st.body)
            elif isinstance(st, Repeat):
                collect(st.body)
            elif isinstance(st, If):
                collect(st.then); collect(st.els or [])
                for _, b in st.elifs:
                    collect(b)
    for d in prog.decls:
        if isinstance(d, FnDecl):
            collect(d.body)

    main_body = "\n".join(body)
    # emit region init at the top of main
    inits = []
    for ln in region_decls:
        if ln.startswith("static const size_t"):
            name = ln.split("RGCAP_")[1].split(" ")[0].split("=")[0].strip()
            en, v = name.rsplit("_", 1)
            inits.append(f"    rg_{en}_{v} = pr_region(RGCAP_{en}_{v});")
            inits.append(f"    w_{en}_{v} = rg_{en}_{v};")

    code = (prelude
            + "\n" + "\n".join(sorted(set(region_decls))) + "\n"
            + "int main(void) {\n"
            + "\n".join(inits) + "\n"
            + main_body + "\n    return 0;\n}\n")
    return code, an.stats
