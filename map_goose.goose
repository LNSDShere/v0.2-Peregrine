// Goose: keys sliced into a byte blob the program owns, stdlib dictionary.
// Pass 1 generates the keys (so the blob stops growing and slices stay
// valid), pass 2 does the counting, then an order-insensitive fold.
import std;
import dictionary;

fn main() {
    var keys: u8[>..] = [];
    var starts: i64[>..] = [];
    var lens: i64[>..] = [];
    var x: i64 = 424242;
    for i in 16000000 {
        x = (x * 1103515245 + 12345) & 4294967295;
        let id = x % 65536;
        starts.push(keys.len);
        format(keys, "user", id);
        lens.push(keys.len - starts[i]);
    }
    var counts = dictionary<u8[:], i64> {};
    for i in 16000000 {
        counts.update(keys[starts[i]..starts[i] + lens[i]], 0) { it += 1; };
    }
    var sum: i64 = 0;
    var wsum: i64 = 0;
    var cnt: i64 = 0;
    counts.each() { w, n => sum += n; };
    counts.each() { w, n => wsum += w.len * n; };
    counts.each() { w, n => cnt += 1; };
    print(cnt, " ", sum, " ", wsum);
}
