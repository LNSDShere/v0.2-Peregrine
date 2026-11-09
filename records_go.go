// Go idiomatic: a slice of interface values with a type switch, the way
// Go models variant records (the analog of std::variant / Rust enums).
// Strings are built per record; the interface headers heap-allocate.
package main

import (
	"fmt"
	"strconv"
)

type Event interface{ isEvent() }

type Login struct {
	User string
	Ts   uint64
}

type Purchase struct {
	User   string
	Ts     uint64
	Amount uint64
	Qty    uint64
}

type Logout struct {
	Ts uint64
}

func (Login) isEvent()    {}
func (Purchase) isEvent() {}
func (Logout) isEvent()   {}

func main() {
	const n = 16000000
	log := make([]Event, 0, n)
	x := uint32(12345)
	for i := uint64(0); i < n; i++ {
		x = x*1103515245 + 12345
		r := uint64(x)
		user := "user" + strconv.FormatUint(r%4096, 10)
		switch r % 3 {
		case 0:
			log = append(log, Login{user, i})
		case 1:
			log = append(log, Purchase{user, i, r % 100000, r % 12})
		default:
			log = append(log, Logout{i})
		}
	}
	var sumTs, bytes, sumAmt, cnt uint64
	for pass := 0; pass < 4; pass++ {
		for _, e := range log {
			switch v := e.(type) {
			case Login:
				sumTs += v.Ts
				bytes += uint64(len(v.User))
				cnt++
			case Purchase:
				sumTs += v.Ts
				bytes += uint64(len(v.User))
				sumAmt += v.Amount
				cnt++
			case Logout:
				sumTs += v.Ts
				cnt++
			}
		}
	}
	fmt.Println(sumTs, bytes, sumAmt, cnt)
}
