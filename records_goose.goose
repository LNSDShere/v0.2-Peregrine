// Goose: build a log of N variant records (Login/Purchase/Logout), then
// aggregate it four times.
import std;

enum Ev {
    Login { user: u8[varint], ts: varint },
    Purchase { user: u8[varint], ts: varint, amount: varint, qty: varint },
    Logout { ts: varint },
}

fn main() {
    var log: Ev..[>..] = [];
    var x: i64 = 12345;
    for i in 16000000 {
        x = (x * 1103515245 + 12345) & 4294967295;
        let r = x;
        var name: u8[>..] = "user";
        format_int(name, r % 4096, 10, 1, '0');
        let v = r % 3;
        if v == 0 {
            log.push(Ev.Login { user: name[..], ts: i });
        } else if v == 1 {
            log.push(Ev.Purchase { user: name[..], ts: i, amount: r % 100000, qty: r % 12 });
        } else {
            log.push(Ev.Logout { ts: i });
        }
    }
    var sum_ts: i64 = 0; var bytes: i64 = 0; var sum_amt: i64 = 0; var cnt: i64 = 0;
    for e in log { match e { Login &l => { sum_ts += l.ts; bytes += l.user.len; cnt += 1; }, Purchase &p => { sum_ts += p.ts; bytes += p.user.len; sum_amt += p.amount; cnt += 1; }, Logout &o2 => { sum_ts += o2.ts; cnt += 1; } } }
    for e in log { match e { Login &l => { sum_ts += l.ts; bytes += l.user.len; cnt += 1; }, Purchase &p => { sum_ts += p.ts; bytes += p.user.len; sum_amt += p.amount; cnt += 1; }, Logout &o2 => { sum_ts += o2.ts; cnt += 1; } } }
    for e in log { match e { Login &l => { sum_ts += l.ts; bytes += l.user.len; cnt += 1; }, Purchase &p => { sum_ts += p.ts; bytes += p.user.len; sum_amt += p.amount; cnt += 1; }, Logout &o2 => { sum_ts += o2.ts; cnt += 1; } } }
    for e in log { match e { Login &l => { sum_ts += l.ts; bytes += l.user.len; cnt += 1; }, Purchase &p => { sum_ts += p.ts; bytes += p.user.len; sum_amt += p.amount; cnt += 1; }, Logout &o2 => { sum_ts += o2.ts; cnt += 1; } } }
    print(sum_ts, " ", bytes, " ", sum_amt, " ", cnt);
}
