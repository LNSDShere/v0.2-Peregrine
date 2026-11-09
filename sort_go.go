// Go: generate 16M pseudo-random u32, slices.Sort, fold a checksum.
package main

import (
	"fmt"
	"slices"
)

func main() {
	const n = 16000000
	a := make([]uint32, n)
	s := uint32(123456789)
	for i := 0; i < n; i++ {
		s = s*1103515245 + 12345
		a[i] = s
	}
	slices.Sort(a)
	var sum uint64
	for _, v := range a {
		sum += uint64(v)
	}
	var asc uint64
	for i := 1; i < n; i++ {
		if a[i] < a[i-1] {
			asc++
		}
	}
	fmt.Println(sum, asc, a[0], a[n-1], n)
}
