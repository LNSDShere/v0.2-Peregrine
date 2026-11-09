// Natural C: malloc'd uint32_t array + qsort with a comparator, built with -O2.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static int cmp_u32(const void* pa, const void* pb) {
    uint32_t x = *(const uint32_t*)pa, y = *(const uint32_t*)pb;
    return (x > y) - (x < y);
}

int main(void) {
    size_t N = 16000000;
    uint32_t* a = malloc(N * sizeof(uint32_t));
    uint32_t s = 123456789;
    for (size_t i = 0; i < N; i++) {
        s = s * 1103515245u + 12345u;
        a[i] = s;
    }
    qsort(a, N, sizeof(uint32_t), cmp_u32);
    uint64_t sum = 0;
    for (size_t i = 0; i < N; i++) sum += a[i];
    uint64_t asc = 0;
    for (size_t i = 1; i < N; i++) {
        if (a[i] < a[i - 1]) asc++;
    }
    printf("%llu %llu %u %u %zu\n", (unsigned long long)sum, (unsigned long long)asc,
           a[0], a[N - 1], N);
    return 0;
}
