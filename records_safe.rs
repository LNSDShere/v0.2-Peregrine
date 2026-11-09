// Safe idiomatic Rust: Vec of enums with owned Strings.
enum Ev {
    Login { user: String, ts: u64 },
    Purchase { user: String, ts: u64, amount: u64, qty: u64 },
    Logout { ts: u64 },
}

fn main() {
    let n: u64 = 16000000;
    let mut log: Vec<Ev> = Vec::new();
    let mut x: u32 = 12345;
    for i in 0..n {
        x = x.wrapping_mul(1103515245).wrapping_add(12345);
        let r = x as u64;
        let user = format!("user{}", r % 4096);
        match r % 3 {
            0 => log.push(Ev::Login { user, ts: i }),
            1 => log.push(Ev::Purchase { user, ts: i, amount: r % 100000, qty: r % 12 }),
            _ => log.push(Ev::Logout { ts: i }),
        }
    }
    let mut sum_ts: u64 = 0;
    let mut bytes: u64 = 0;
    let mut sum_amt: u64 = 0;
    let mut cnt: u64 = 0;
    for _ in 0..4 {
        for e in &log {
            match e {
                Ev::Login { user, ts } => { sum_ts += ts; bytes += user.len() as u64; cnt += 1; }
                Ev::Purchase { user, ts, amount, .. } => { sum_ts += ts; bytes += user.len() as u64; sum_amt += amount; cnt += 1; }
                Ev::Logout { ts } => { sum_ts += ts; cnt += 1; }
            }
        }
    }
    println!("{} {} {} {}", sum_ts, bytes, sum_amt, cnt);
}
