// Idiomatic C++: std::variant + std::string + std::vector, no reserve games.
#include <cstdint>
#include <cstdio>
#include <string>
#include <variant>
#include <vector>

struct Login { std::string user; uint64_t ts; };
struct Purchase { std::string user; uint64_t ts; uint64_t amount; uint64_t qty; };
struct Logout { uint64_t ts; };
using Ev = std::variant<Login, Purchase, Logout>;

int main() {
    std::vector<Ev> log;
    uint32_t x = 12345;
    for (uint64_t i = 0; i < 16000000; i++) {
        x = x * 1103515245u + 12345u;
        uint64_t r = x;
        char buf[16];
        snprintf(buf, sizeof buf, "user%llu", (unsigned long long)(r % 4096));
        std::string user = buf;
        switch (r % 3) {
            case 0: log.push_back(Login{user, i}); break;
            case 1: log.push_back(Purchase{user, i, r % 100000, r % 12}); break;
            default: log.push_back(Logout{i}); break;
        }
    }
    uint64_t sum_ts = 0, bytes = 0, sum_amt = 0, cnt = 0;
    for (int pass = 0; pass < 4; pass++) {
        for (const Ev& e : log) {
            if (auto l = std::get_if<Login>(&e)) { sum_ts += l->ts; bytes += l->user.size(); cnt++; }
            else if (auto p = std::get_if<Purchase>(&e)) { sum_ts += p->ts; bytes += p->user.size(); sum_amt += p->amount; cnt++; }
            else { sum_ts += std::get<Logout>(e).ts; cnt++; }
        }
    }
    printf("%llu %llu %llu %llu\n", (unsigned long long)sum_ts, (unsigned long long)bytes,
           (unsigned long long)sum_amt, (unsigned long long)cnt);
    return 0;
}
