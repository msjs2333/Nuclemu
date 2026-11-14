#!/bin/bash
# Minimal declared-system-library image: no host Python or Node and no display.
set -euo pipefail
artifacts=${1:?artifact directory required}
output=${2:?output directory required}
test "$(id -u)" = 0
test "$(ls /sys/class/net)" = lo
if command -v python3 || command -v node; then
    echo 'Unexpected system Python or Node in minimal runtime image' >&2
    exit 1
fi
test -z "${DISPLAY:-}"
mkdir -p "$output" /tmp/app
chown student:student "$output" /tmp/app
runuser -u student -- tar -xzf "$artifacts/nuclemu-0.0.1-1-linux-amd64.tar.gz" -C /tmp/app
cli=/tmp/app/nuclemu-0.0.1/nuclemu
while IFS= read -r -d '' library; do
    LD_LIBRARY_PATH=/tmp/app/nuclemu-0.0.1/_internal ldd "$library" >> "$output/ldd.txt"
done < <(find /tmp/app/nuclemu-0.0.1/_internal -type f -name '*.so*' -print0)
if grep -q 'not found' "$output/ldd.txt"; then
    cat "$output/ldd.txt" >&2
    exit 1
fi
runuser -u student -- "$cli" validate
runuser -u student -- "$cli" run beta --set source_present=1 --enable-output beta_detector --seed 187 --window counter=1 --window counter_b=5 --duration 3 --package "$output/beta.nuclemu"
runuser -u student -- "$cli" files inspect "$output/beta.nuclemu" > "$output/inspect.json"
set +e
runuser -u student -- "$cli" serve --gui > "$output/gui.out" 2> "$output/gui.err"
code=$?
set -e
test "$code" = 2
grep -q 'serve --no-gui' "$output/gui.err"
# GNU timeout signals the real foreground process; 124 means its deadline fired.
set +e
runuser -u student -- timeout --signal=INT --kill-after=5 3 "$cli" serve --no-gui > "$output/service.out" 2> "$output/service.err"
code=$?
set -e
test "$code" = 124
grep -q 'http://127.0.0.1:' "$output/service.out"
test ! -s "$output/service.err"
printf 'PASS: declared libraries only, no Python/Node/display/network, bundled CLI and headless service.\n' | tee "$output/passed"
