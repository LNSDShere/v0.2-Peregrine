// Safe idiomatic Rust: Vec of 16-byte records, sort_unstable_by_key, rustc -O.
#[derive(Clone, Copy)]
struct Rec {
    k: u64,
    v: u64,
}

fn main() {
    let n: u64 = 16000000;
    let mut a: Vec<Rec> = Vec::with_capacity(n as usize);
    let mut s: u64 = 88172645463325252;
    for _ in 0..n {
        s = s.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        a.push(Rec { k: s, v: s.wrapping_mul(2654435761) });
    }
    a.sort_unstable_by_key(|r| r.k);
    let mut sumk: u64 = 0;
    let mut xk: u64 = 0;
    for r in &a {
        sumk = sumk.wrapping_add(r.k);
        xk ^= r.k.wrapping_add(r.v);
    }
    let mut asc: u64 = 0;
    for i in 1..n {
        if a[i as usize].k < a[i as usize - 1].k {
            asc += 1;
        }
    }
    println!("{} {} {} {} {} {}", sumk, xk, asc, a[0].k, a[n as usize - 1].k, n);
}
