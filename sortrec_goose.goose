// Goose: array of 16-byte records, stdlib sort by key, same checksum.
import std;

struct Rec { k: u64, v: u64 }

fn main() {
    var a: Rec[>..] = [];
    var s: u64 = 88172645463325252;
    for i in 16000000 {
        s = s * 6364136223846793005 + 1442695040888963407;
        a.push(Rec { k: s, v: s * 2654435761 });
    }
    sort(a) { x, y => x.k < y.k };
    var sumk: u64 = 0;
    var xk: u64 = 0;
    for r in a {
        sumk += r.k;
        xk = xk ^ (r.k + r.v);
    }
    var asc: u64 = 0;
    for i in 16000000 {
        if i > 0 && a[i].k < a[i - 1].k { asc += 1; }
    }
    print(sumk, " ", xk, " ", asc, " ", a[0].k, " ", a[15999999].k, " ", 16000000);
}
