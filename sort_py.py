# Pure CPython: LCG into a list, list.sort(), fold a checksum.
import os

M32 = 0xFFFFFFFF
N = int(os.environ.get("BENCH_N", "16000000"))

a = [0] * N
s = 123456789
for i in range(N):
    s = (s * 1103515245 + 12345) & M32
    a[i] = s

a.sort()

total = 0
for v in a:
    total += v

asc = 0
for i in range(1, N):
    if a[i] < a[i - 1]:
        asc += 1

print(total, asc, a[0], a[N - 1], N)
