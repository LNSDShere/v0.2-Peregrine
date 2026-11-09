# The Peregrine Programming Language — v0.2

Peregrine is a small compiled systems language built around one idea:
**the compiler, not the programmer, produces the fast shape.** It tracks a
provable `[lo, hi]` range for every integer expression, stores fields at
the smallest width their values provably occupy, segregates enum stores
per variant, builds strings in place, keys maps by inline bytes, lowers
`sort()` to a radix sort, and emits `omp simd` only on loops it has proven
safe to vectorize. It compiles to one C file built by the machine's C
compiler. No garbage collector, no heap allocator for program data, no
nil pointers, no undefined behavior.

## Core ideas

### 1. Range-proven widths

```
let v = r % 3;          // provably [0, 2]
amount = r % 100000     // provably [0, 99999]  -> stored in 3 bytes
qty     = r % 12        // provably [0, 11]     -> stored in 1 byte
```

Fields written through `push` are physically stored at the smallest width
their proven range needs (`u8`/`u16`/`u24`/`u32`/`u64`). Unprovable values
get a runtime check naming the source line instead of silent truncation.
`--stats` reports what was proven and what was checked.

### 2. Stores: variant-segregated regions

```
var log: store<Ev>(N);
log.push(Ev.Login { user: user, ts: i });
for e in log { match e { Login(l) => ..., Purchase(p) => ..., Logout(o) => ... } }
```

A store reserves one virtual region per enum variant (worst-case record
size x capacity, touched pages only). Each push appends into its variant's
region; iteration compiles to one branch-free sequential scan per variant.
**Store order is unspecified** — a store is a bag; aggregation must be
order-insensitive (sums, counts, min/max). The language says so instead of
hiding it.

### 3. Strings built in place

`"user" + str(r % 4096)` is a *build plan* materialized directly into the
destination bytes — no intermediate string object, no allocation, no copy.
Plan shapes: a literal, `str(int)`, or literal + `str(int)`.

### 4. Buffers, maps, sort

```
var a: buf<u32>(N);            // restrict-qualified, page-backed, zeroed
a[i] = h;                      // proof-or-check indexing
sort(a);                       // LSD radix, 16-bit digits, no comparators
sort(k, v);                    // radix carrying a u64 payload
var counts: map<str, u64>(SLOTS);   // open addressing, inline keys
counts.bump("user" + str(id));      // key built in place into the probe
for kv in counts { ... kv.val ... kv.key.len ... }   // slot order unspecified
```

`map` slots are 32 bytes: FNV-1a tag, inline key up to 19 bytes, linear
probing, no tombstones, insert-past-capacity traps with a named error.

### 5. Automatic SIMD

A `for i in a..b` loop the compiler proves free of traps, calls, string
plans and loop-carried scalar dependencies (other than `+`/`^`
accumulators, which become `reduction(...)` clauses) and whose every index
is proven in bounds is emitted under `#pragma omp simd`. Anything else
stays scalar — pragmas are never applied speculatively. Release build:
`gcc -O3 -march=native -fopenmp-simd -fsimd-cost-model=unlimited
-mprefer-vector-width=512 -funroll-loops`.

### 6. Safety

Wrapping is defined; out-of-bounds is a clean trap elided only by proof;
div/mod by zero traps; map overflow traps; there is no pointer type, no
cast, no `unsafe`.

## Grammar (v0.2)

```
program   := (const | enum | fn)*
const     := 'const' IDENT ':' ('u32'|'u64') '=' int ';'
enum      := 'enum' IDENT '{' IDENT '{' field (',' field)* '}' ... '}'
field     := IDENT ':' ('u8'|'u16'|'u32'|'u64'|'str')
fn        := 'fn' 'main' '(' ')' block
stmt      := var | let | assign | indexassign | for | repeat | if | match
           | print | push | methodcall | call
type      := ('u32'|'u64') | 'store' '<' IDENT '>' '(' cexpr ')'
           | 'buf' '<' ('u32'|'u64') '>' '(' cexpr ')'
           | 'map' '<' 'str' ',' 'u64' '>' '(' cexpr ')'
for       := 'for' IDENT 'in' cexpr '..' cexpr block
           | 'for' IDENT 'in' (store | map) block
match     := 'match' IDENT '{' Variant '(' IDENT? ')' '=>' block ... '}'
push      := IDENT '.' 'push' '(' Enum.Variant '{' f: e, ... '}' ')' ';'
method    := IDENT '.' 'bump' '(' keyexpr (',' delta)? ')' ';'
call      := 'sort' '(' buf (',' buf)? ')' ';'
print     := 'print' '(' (expr (',' expr)*)? ')' ';'
expr      := literals, names, field paths (a.b.c), + - * / %, << >> & ^ |,
             < > <= >=, == !=, str(int), "lit" + str(int), Enum.Variant {...},
             buf indexing
binders   := store binder: f, strf.len; map binder: kv.val, kv.key.len
precedence: additive (+ -) < relational (< > <= >=) < equality (== !=)
           < shift (<< >>) < bitwise (& ^ |) < multiplicative (* / %)
```

## Honest limitations (v0.2)

- One function (`main`); no user-defined functions, no generics.
- Match is only valid as a store for-in body; binders expose fields and
  `strfield.len`, not string values.
- Range proofs cover literals, consts, loop induction over constant
  bounds, `% c`, `>> c`, `& c`. Real analysis, not constant folding.
- Map keys are inline (max 19 bytes); bump-only: no remove, no resize.
- `sort(k, v)`'s payload radix is honest engineering, not world-class: on
  16-byte records a naive 16-bit-digit scatter loses to Rust's pdqsort at
  16M records (measured). Single-buffer machine-word `sort()` wins its
  class. Specializing payload scatters is future work.
- SIMD eligibility is conservative (an `if`, an unproven index or a
  non-reduction carried scalar makes the loop scalar).
- The compiler is ~1,800 lines of readable Python (front.py + backend.py)
  you can audit in an afternoon.
