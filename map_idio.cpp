// Idiomatic C++: unordered_map<string,uint64_t>, built with -O2.
#include <cstdint>
#include <cstdio>
#include <string>
#include <unordered_map>

int main() {
    const uint64_t N = 16000000;
    const uint32_t KEYS = 65536;
    std::unordered_map<std::string, uint64_t> counts;
    uint32_t s = 424242;
    for (uint64_t i = 0; i < N; i++) {
        s = s * 1103515245u + 12345u;
        counts["user" + std::to_string(s % KEYS)]++;
    }
    uint64_t sum = 0, wsum = 0, cnt = 0;
    for (const auto& kv : counts) {
        sum += kv.second;
        wsum += (uint64_t)kv.first.size() * kv.second;
        cnt++;
    }
    printf("%llu %llu %llu\n", (unsigned long long)cnt, (unsigned long long)sum,
           (unsigned long long)wsum);
    return 0;
}
