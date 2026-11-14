#!/bin/bash
# Run on a native macOS host; downloads are build-time only.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$PWD"
ARCH="${1:-$(uname -m)}"
[[ "$(uname -s)" == Darwin ]] || { echo 'Build on macOS.' >&2; exit 2; }
[[ "$ARCH" == x86_64 || "$ARCH" == arm64 ]] || { echo 'Expected x86_64 or arm64.' >&2; exit 2; }
[[ "$(uname -m)" == "$ARCH" ]] || { echo 'Use a native runner for each architecture.' >&2; exit 2; }
WORK="$ROOT/build/macos/$ARCH"
OUT="$ROOT/dist/macos/$ARCH"
mkdir -p "$WORK" "$OUT"
PYTHON_VERSION=3.14.10
PKG="$WORK/python-$PYTHON_VERSION-macos11.pkg"
curl --fail --location --retry 3 "https://www.python.org/ftp/python/$PYTHON_VERSION/python-$PYTHON_VERSION-macos11.pkg" -o "$PKG"
echo "286c7018aa2730f6747ca433dccdc2b31be45f078a9ea0ffa44d5f06368fd2d7  $PKG" | shasum -a 256 -c -
pkgutil --check-signature "$PKG" | tee "$WORK/python-signature.txt"
grep -F 'Python Software Foundation' "$WORK/python-signature.txt" >/dev/null
sudo installer -pkg "$PKG" -target /
PYTHON=/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14
"$PYTHON" -m venv "$WORK/venv"
PYTHON="$WORK/venv/bin/python"
"$PYTHON" -m pip install PyInstaller==6.20.0 pyinstaller-hooks-contrib==2026.10
"$PYTHON" -c 'import platform, tkinter, sqlite3; print(platform.machine(), tkinter.Tcl().eval("info patchlevel"), sqlite3.sqlite_version)'
test -s nuclemu/static/index.html
# Generate an Apple icon from the repository's bitmap, using native tools only.
ICONSET="$WORK/Nuclemu.iconset"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" nuclemu/static/nuclemu-mark.png --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" nuclemu/static/nuclemu-mark.png --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$WORK/Nuclemu.icns"
export NUCLEMU_MAC_ARCH="$ARCH" NUCLEMU_MAC_ICON="$WORK/Nuclemu.icns"
"$PYTHON" -m PyInstaller --clean --noconfirm --workpath "$WORK/freeze" --distpath "$OUT" packaging/macos/nuclemu.spec
APP="$OUT/Nuclemu.app"
echo 2 > "$APP/Contents/Resources/package-revision.txt"
codesign --force --deep --sign - "$APP"
"$APP/Contents/MacOS/nuclemu-cli" --bundle-check > "$OUT/runtime-check.json"
codesign --verify --deep --strict --verbose=2 "$APP"
"$PYTHON" - "$OUT" "$ARCH" <<'PY'
from importlib.metadata import version
from pathlib import Path
import json, platform, subprocess, sys, tomllib
out, architecture = Path(sys.argv[1]), sys.argv[2]
project_version = tomllib.loads(Path('pyproject.toml').read_text())['project']['version']
info = dict(version=project_version, architecture=architecture, python=sys.version,
    pyinstaller=version('pyinstaller'), hooks=version('pyinstaller-hooks-contrib'),
    macos=platform.mac_ver()[0], commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
    package_revision=2, signature='ad-hoc', notarized=False, desktop_acceptance='pending')
(out / 'build-info.json').write_text(json.dumps(info, indent=2) + '\n')
(out / 'version.txt').write_text(project_version)
PY
VERSION="$(cat "$OUT/version.txt")"
STAGE="$(mktemp -d "$WORK/dmg-root.XXXXXX")"
ditto "$APP" "$STAGE/Nuclemu.app"
ln -s /Applications "$STAGE/Applications"
cp packaging/macos/README.md "$STAGE/README.md"
cp "$OUT/build-info.json" "$STAGE/build-info.json"
DMG="$OUT/Nuclemu-$VERSION-macos-$ARCH.dmg"
hdiutil create -ov -format UDZO -fs HFS+ -volname Nuclemu -srcfolder "$STAGE" "$DMG"
# A distinct earlier packaging revision tests replacement and removed resources.
# Its Python/model/frontend payload is identical; this is not a cross-version claim.
plutil -replace CFBundleVersion -string 1 "$STAGE/Nuclemu.app/Contents/Info.plist"
echo 1 > "$STAGE/Nuclemu.app/Contents/Resources/package-revision.txt"
echo 'Only in package revision 1' > "$STAGE/Nuclemu.app/Contents/Resources/obsolete-revision-1.txt"
"$PYTHON" - "$STAGE/build-info.json" <<'PY'
from pathlib import Path
import json, sys
path = Path(sys.argv[1])
info = json.loads(path.read_text())
info.update(package_revision=1, candidate='upgrade-smoke-baseline')
path.write_text(json.dumps(info, indent=2) + '\n')
PY
codesign --force --deep --sign - "$STAGE/Nuclemu.app"
PREVIOUS="$OUT/Nuclemu-$VERSION-macos-$ARCH-r1.dmg"
hdiutil create -ov -format UDZO -fs HFS+ -volname Nuclemu-r1 -srcfolder "$STAGE" "$PREVIOUS"
(cd "$OUT" && shasum -a 256 "$(basename "$DMG")" "$(basename "$PREVIOUS")" > SHA256SUMS)
echo "Built $DMG"
