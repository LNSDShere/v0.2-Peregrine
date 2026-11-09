#!/bin/bash
# Build every implementation of every benchmark, print checksums.
set -e
cd /home/z/my-project/scripts/verify
export RUSTUP_HOME=/home/z/.rustup CARGO_HOME=/home/z/.cargo
export PATH=/home/z/.cargo/bin:$PATH
export GOOSE_HOME=/home/z/my-project/.tools/goose_home
export GOCACHE=/home/z/my-project/.tools/go-cache GOPATH=/home/z/my-project/.tools/gopath
G=/home/z/my-project/.tools/goose-repo/goose_bin
GO=/home/z/my-project/.tools/go/bin/go
P="python3 /home/z/my-project/scripts/peregrine/peregrine_cli.py"

for b in mix sort map sortrec records; do
  echo "=== $b ==="
  case $b in
    mix) SRC=mix_prn.peregrine; IMPLS="mix_c.c:mix_c mix_idio.cpp:mix_cpp_idio mix_safe.rs:mix_rust_safe mix_goose.goose:mix_goose mix_go.go:mix_go";;
    sort) SRC=sort_prn.peregrine; IMPLS="sort_c.c:sort_c sort_idio.cpp:sort_cpp_idio sort_safe.rs:sort_rust_safe sort_goose.goose:sort_goose sort_go.go:sort_go";;
    map) SRC=map_prn.peregrine; IMPLS="map_c.c:map_c map_idio.cpp:map_cpp_idio map_safe.rs:map_rust_safe map_goose.goose:map_goose map_go.go:map_go";;
    sortrec) SRC=sortrec_prn.peregrine; IMPLS="sortrec_c.c:sortrec_c sortrec_idio.cpp:sortrec_cpp_idio sortrec_safe.rs:sortrec_rust_safe sortrec_goose.goose:sortrec_goose";;
    records) SRC=records.peregrine; IMPLS="records_idio.cpp:records_cpp_idio records_safe.rs:records_rust_safe records_goose.goose:records_goose records_go.go:records_go";;
  esac
  python3 /home/z/my-project/scripts/peregrine/peregrine_cli.py $SRC --exe ${b}_prn --stats | tail -1
  for impl in $IMPLS; do
    src="${impl%%:*}"; out="${impl##*:}"
    case $src in
      *.c) gcc -O2 $src -o $out;;
      *.cpp) g++ -O2 -std=c++20 $src -o $out;;
      *.rs) rustc -O -C codegen-units=1 --edition 2021 $src -o $out;;
      *.goose) $G build $src --cc gcc -o $out 2>&1 | tail -1;;
      *.go) $GO build -o $out $src;;
    esac
  done
done

echo "=== checksums ==="
for b in mix sort map sortrec records; do
  echo "-- $b"
  for i in ${b}_prn ${b}_c ${b}_cpp_idio ${b}_rust_safe ${b}_goose ${b}_go; do
    [ -x ./$i ] && { printf '%-18s ' $i; ./$i; }
  done
done
