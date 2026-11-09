// Goose: fixed u32 array, stdlib sort (comparison sort), same checksum.
import std;

fn main() {
    var a: u32[16000000] = [0; 16000000];
    var s: u32 = 123456789;
    for i in 16000000 {
        s = s * 1103515245 + 12345;
        a[i] = s;
    }
    sort(a);
    var sum: i64 = 0;
    for i in 16000000 { sum += a[i]; }
    var asc: i64 = 0;
    for i in 16000000 {
        if i > 0 && a[i] < a[i - 1] { asc += 1; }
    }
    print(sum, " ", asc, " ", a[0], " ", a[15999999], " ", 16000000);
}
