# Pure CPython: tagged tuples (the common fast idiom for variant records),
# built per record, aggregated four times.
import os

M32 = 0xFFFFFFFF
N = int(os.environ.get("BENCH_N", "16000000"))

log = []
x = 12345
for i in range(N):
    x = (x * 1103515245 + 12345) & M32
    r = x
    user = "user" + str(r % 4096)
    v = r % 3
    if v == 0:
        log.append((0, user, i, 0, 0))
    elif v == 1:
        log.append((1, user, i, r % 100000, r % 12))
    else:
        log.append((2, "", i, 0, 0))

sum_ts = 0
nbytes = 0
sum_amt = 0
cnt = 0
for _ in range(4):
    for e in log:
        k = e[0]
        if k == 0:
            sum_ts += e[2]
            nbytes += len(e[1])
            cnt += 1
        elif k == 1:
            sum_ts += e[2]
            nbytes += len(e[1])
            sum_amt += e[3]
            cnt += 1
        else:
            sum_ts += e[2]
            cnt += 1

print(sum_ts, nbytes, sum_amt, cnt)
