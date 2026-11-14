#!/bin/bash
# Run only in a disposable acceptance container, as root, with --network none.
set -euo pipefail
artifacts=${1:?artifact directory required}
samples=${2:?sample directory required}
evidence=${3:?fresh evidence directory required}
recipes=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test "$(id -u)" = 0
test -f "$artifacts/nuclemu_0.0.1-0_amd64.deb"
test -f "$artifacts/nuclemu_0.0.1-1_amd64.deb"
test -f "$artifacts/nuclemu-0.0.1-1-linux-amd64.tar.gz"
mkdir -p "$evidence"
test ! -e "$evidence/started"
date -u +%FT%TZ > "$evidence/started"
exec > >(tee "$evidence/acceptance.log") 2>&1
uname -a
cat /etc/os-release
ldd --version | head -n 1
test "$(ls /sys/class/net)" = lo
chown student:student "$evidence"
student() { runuser -u student -- "$@"; }
headless() { student env -u DISPLAY -u WAYLAND_DISPLAY python3 "$recipes/verify.py" --cli "$1" --samples "$samples" --output "$2"; }
cleanup() {
    pkill -u student -x nuclemu 2>/dev/null || true
    pkill -u student -f firefox-esr 2>/dev/null || true
    test -z "${wm_pid:-}" || kill "$wm_pid" 2>/dev/null || true
    test -z "${x_pid:-}" || kill "$x_pid" 2>/dev/null || true
}
trap cleanup EXIT

dpkg -i "$artifacts/nuclemu_0.0.1-0_amd64.deb"
test "$(dpkg-query -W -f='${Version}' nuclemu)" = 0.0.1-0
headless /usr/bin/nuclemu "$evidence/installed-candidate0"
student sh -c 'mkdir -p "$HOME/.nuclemu" "$HOME/Documents/Lab files"; printf "%s\n" "{\"port\":18861,\"open_browser\":false}" > "$HOME/.nuclemu/launcher.json"'
student cp "$samples/AEL.nuclemu" '/home/student/Documents/Lab files/AEL.nuclemu'
student cp "$samples/BABS.nuclemu" '/home/student/Documents/Lab files/BABS.nuclemu'
sha256sum /home/student/.nuclemu/launcher.json /home/student/Documents/'Lab files'/*.nuclemu > "$evidence/user-before.sha256"

dpkg -i "$artifacts/nuclemu_0.0.1-1_amd64.deb"
test "$(dpkg-query -W -f='${Version}' nuclemu)" = 0.0.1-1
sha256sum -c "$evidence/user-before.sha256"
headless /usr/bin/nuclemu "$evidence/installed-upgraded"
desktop-file-validate /usr/share/applications/nuclemu.desktop
test "$(grep '^Terminal=' /usr/share/applications/nuclemu.desktop)" = Terminal=false
Xvfb :99 -screen 0 1280x900x24 -ac > "$evidence/xvfb.log" 2>&1 & x_pid=$!
export DISPLAY=:99
openbox > "$evidence/openbox.log" 2>&1 & wm_pid=$!
sleep 1
student env DISPLAY=:99 dbus-run-session -- gtk-launch nuclemu
python3 - <<'PY'
import json,time,urllib.request
for attempt in range(100):
    try:
        with urllib.request.urlopen('http://127.0.0.1:18861/api/catalog',timeout=.5) as response:
            assert {r['id'] for r in json.load(response)['experiments']} == {'alpha','beta'}
        break
    except OSError:
        time.sleep(.1)
else:
    raise AssertionError('Menu-launched service did not become ready at saved port')
PY
window=$(xdotool search --sync --onlyvisible --name '^Nuclemu$' | head -n 1)
xdotool getwindowgeometry "$window" | tee "$evidence/menu-window.txt"
scrot "$evidence/menu-launch.png"
# A second entry activates the same desktop, never a second listener/window.
student /usr/bin/nuclemu serve --gui
test "$(xdotool search --onlyvisible --name '^Nuclemu$' | wc -l)" = 1
xdotool windowactivate --sync "$window"
xdotool key --clearmodifiers alt+F4
python3 - <<'PY'
import socket,time
for attempt in range(100):
    try:
        with socket.create_connection(('127.0.0.1',18861),timeout=.1): pass
    except OSError: break
    time.sleep(.1)
else: raise AssertionError('Desktop listener survived idle close')
PY
sha256sum -c "$evidence/user-before.sha256"
dpkg -r nuclemu
test ! -e /usr/bin/nuclemu
test ! -e /usr/bin/nuclemu-desktop
test ! -e /usr/share/applications/nuclemu.desktop
test ! -e /opt/nuclemu
sha256sum -c "$evidence/user-before.sha256"

student mkdir -p '/home/student/便携 实验'
student tar -xzf "$artifacts/nuclemu-0.0.1-1-linux-amd64.tar.gz" -C '/home/student/便携 实验'
headless '/home/student/便携 实验/nuclemu-0.0.1/nuclemu' "$evidence/portable"
student mv '/home/student/便携 实验/nuclemu-0.0.1' '/home/student/便携 实验/relocated lab'
headless '/home/student/便携 实验/relocated lab/nuclemu' "$evidence/portable-relocated"
sha256sum -c "$evidence/user-before.sha256"
printf 'PASS: installed, upgraded, menu launched, removed, portable relocated, preferences and files preserved.\n'
date -u +%FT%TZ > "$evidence/passed"
