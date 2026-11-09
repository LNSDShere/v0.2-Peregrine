// Safe idiomatic Rust: Vec<u32> + sort_unstable, built with rustc -O.
fn main() {
    let n: u64 = 16000000;
    let mut a = vec![0u32; n as usize];
    let mut s: u32 = 123456789;
    for i in 0..n {
        s = s.wrapping_mul(1103515245).wrapping_add(12345);
        a[i as usize] = s;
    }
    a.sort_unstable();
    let mut sum: u64 = 0;
    for i in 0..n {
        sum += a[i as usize] as u64;
    }
    let mut asc: u64 = 0;
    for i in 1..n {
        if a[i as usize] < a[i as usize - 1] {
            asc += 1;
        }
    }
    println!("{} {} {} {} {}", sum, asc, a[0], a[n as usize - 1], n);
}
