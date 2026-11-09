# Pure CPython: dict counting with per-op string building.
import os

M32 = 0xFFFFFFFF
N = int(os.environ.get("BENCH_N", "16000000"))
KEYS = 65536

counts = {}
s = 424242
for _ in range(N):
    s = (s * 1103515245 + 12345) & M32
    key = "user" + str(s % KEYS)
    counts[key] = counts.get(key, 0) + 1

total = 0
wsum = 0
cnt = 0
for k, v in counts.items():
    total += v
    wsum += len(k) * v
    cnt += 1

print(cnt, total, wsum)
