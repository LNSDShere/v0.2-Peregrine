// Idiomatic C++: vector of 16-byte records, std::sort by key, built with -O2.
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <vector>

struct Rec { uint64_t k, v; };

int main() {
    const uint64_t N = 16000000;
    std::vector<Rec> a;
    a.reserve(N);
    uint64_t s = 88172645463325252ull;
    for (uint64_t i = 0; i < N; i++) {
        s = s * 6364136223846793005ull + 1442695040888963407ull;
        a.push_back(Rec{s, s * 2654435761ull});
    }
    std::sort(a.begin(), a.end(),
              [](const Rec& x, const Rec& y) { return x.k < y.k; });
    uint64_t sumk = 0, xk = 0;
    for (const Rec& r : a) {
        sumk += r.k;
        xk ^= r.k + r.v;
    }
    uint64_t asc = 0;
    for (uint64_t i = 1; i < N; i++) {
        if (a[i].k < a[i - 1].k) asc++;
    }
    printf("%llu %llu %llu %llu %llu %llu\n", (unsigned long long)sumk,
           (unsigned long long)xk, (unsigned long long)asc, a[0].k, a[N - 1].k,
           (unsigned long long)N);
    return 0;
}
