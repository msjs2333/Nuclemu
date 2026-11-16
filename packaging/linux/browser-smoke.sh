#!/bin/bash
# Disposable container only: install the candidate and exercise desktop->Firefox.
set -euo pipefail
artifacts=${1:?artifact directory required}
samples=${2:?sample directory required}
output=${3:?output directory required}
recipes=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test "$(id -u)" = 0
test "$(ls /sys/class/net)" = lo
mkdir -p "$output"
chown student:student "$output"
exec > >(tee "$output/acceptance.log") 2>&1
dpkg -i "$artifacts/nuclemu_0.0.1-1_amd64.deb"
cleanup() {
    pkill -u student -x nuclemu 2>/dev/null || true
    pkill -u student -f firefox-esr 2>/dev/null || true
    kill "$wm_pid" "$x_pid" 2>/dev/null || true
}
Xvfb :99 -screen 0 1280x900x24 -ac > "$output/xvfb.log" 2>&1 & x_pid=$!
export DISPLAY=:99
openbox > "$output/openbox.log" 2>&1 & wm_pid=$!
trap cleanup EXIT
sleep 1
runuser -u student -- env DISPLAY=:99 XDG_CURRENT_DESKTOP=OPENBOX \
    MOZ_DISABLE_CONTENT_SANDBOX=1 MOZ_ENABLE_WAYLAND=0 GDK_BACKEND=x11 GTK_USE_PORTAL=0 \
    dbus-run-session -- python3 "$recipes/browser-check.py" --samples "$samples" --output "$output/browser"
chmod -R a+rX "$output"
