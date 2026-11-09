// Idiomatic C++: std::vector<uint32_t> + std::sort, built with -O2.
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <vector>

int main() {
    const uint64_t N = 16000000;
    std::vector<uint32_t> a(N);
    uint32_t s = 123456789;
    for (uint64_t i = 0; i < N; i++) {
        s = s * 1103515245u + 12345u;
        a[i] = s;
    }
    std::sort(a.begin(), a.end());
    uint64_t sum = 0;
    for (uint64_t i = 0; i < N; i++) sum += a[i];
    uint64_t asc = 0;
    for (uint64_t i = 1; i < N; i++) {
        if (a[i] < a[i - 1]) asc++;
    }
    printf("%llu %llu %u %u %llu\n", (unsigned long long)sum, (unsigned long long)asc,
           a[0], a[N - 1], (unsigned long long)N);
    return 0;
}
