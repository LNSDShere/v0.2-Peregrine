// Natural C: malloc'd 16-byte records, qsort by key, built with -O2.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct { uint64_t k, v; } Rec;

static int cmp_rec(const void* pa, const void* pb) {
    uint64_t x = ((const Rec*)pa)->k, y = ((const Rec*)pb)->k;
    return (x > y) - (x < y);
}

int main(void) {
    size_t N = 16000000;
    Rec* a = malloc(N * sizeof(Rec));
    uint64_t s = 88172645463325252ull;
    for (size_t i = 0; i < N; i++) {
        s = s * 6364136223846793005ull + 1442695040888963407ull;
        a[i].k = s;
        a[i].v = s * 2654435761ull;
    }
    qsort(a, N, sizeof(Rec), cmp_rec);
    uint64_t sumk = 0, xk = 0;
    for (size_t i = 0; i < N; i++) {
        sumk += a[i].k;
        xk ^= a[i].k + a[i].v;
    }
    uint64_t asc = 0;
    for (size_t i = 1; i < N; i++) {
        if (a[i].k < a[i - 1].k) asc++;
    }
    printf("%llu %llu %llu %llu %llu %zu\n", (unsigned long long)sumk,
           (unsigned long long)xk, (unsigned long long)asc, a[0].k, a[N - 1].k,
           N);
    return 0;
}
