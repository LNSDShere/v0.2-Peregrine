// Natural C: hand-rolled open-addressing table with inline keys, -O2.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { char key[16]; uint64_t val; } ent;

static ent* tbl;
static size_t mask;

static uint64_t h_str(const char* p) {
    uint64_t h = 14695ull;
    while (*p) { h ^= (uint8_t)*p++; h *= 1099511628211ull; }
    return h;
}

static void bump(const char* k) {
    size_t i = (size_t)(h_str(k) & mask);
    while (tbl[i].key[0]) {
        if (strcmp(tbl[i].key, k) == 0) { tbl[i].val++; return; }
        i = (i + 1) & mask;
    }
    strcpy(tbl[i].key, k);
    tbl[i].val = 1;
}

int main(void) {
    size_t slots = 131072;
    mask = slots - 1;
    tbl = calloc(slots, sizeof(ent));
    uint32_t s = 424242;
    char buf[16];
    for (uint64_t i = 0; i < 16000000; i++) {
        s = s * 1103515245u + 12345u;
        snprintf(buf, sizeof buf, "user%u", s % 65536u);
        bump(buf);
    }
    uint64_t sum = 0, wsum = 0, cnt = 0;
    for (size_t i = 0; i < slots; i++) {
        if (tbl[i].key[0]) {
            sum += tbl[i].val;
            wsum += (uint64_t)strlen(tbl[i].key) * tbl[i].val;
            cnt++;
        }
    }
    printf("%llu %llu %llu\n", (unsigned long long)cnt, (unsigned long long)sum,
           (unsigned long long)wsum);
    return 0;
}
