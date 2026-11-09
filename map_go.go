// Go: 16M dictionary bumps over 64K distinct generated keys, then an
// order-insensitive fold. Keys are built per op with strconv (the common
// perf-conscious Go idiom; fmt.Sprintf is slower still).
package main

import (
	"fmt"
	"strconv"
)

func main() {
	const n = 16000000
	const keys = 65536
	counts := make(map[string]uint64)
	s := uint32(424242)
	for i := 0; i < n; i++ {
		s = s*1103515245 + 12345
		key := "user" + strconv.FormatUint(uint64(s%keys), 10)
		counts[key]++
	}
	var sum, wsum, cnt uint64
	for k, v := range counts {
		sum += v
		wsum += uint64(len(k)) * v
		cnt++
	}
	fmt.Println(cnt, sum, wsum)
}
