// Safe idiomatic Rust: HashMap<String,u64>, built with rustc -O.
use std::collections::HashMap;

fn main() {
    let n: u64 = 16000000;
    let keys_n: u32 = 65536;
    let mut counts: HashMap<String, u64> = HashMap::new();
    let mut s: u32 = 424242;
    for _ in 0..n {
        s = s.wrapping_mul(1103515245).wrapping_add(12345);
        let key = format!("user{}", s % keys_n);
        *counts.entry(key).or_insert(0) += 1;
    }
    let mut sum: u64 = 0;
    let mut wsum: u64 = 0;
    let mut cnt: u64 = 0;
    for (k, v) in &counts {
        sum += *v;
        wsum += (k.len() as u64) * *v;
        cnt += 1;
    }
    println!("{} {} {}", cnt, sum, wsum);
}
