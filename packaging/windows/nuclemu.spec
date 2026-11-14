"""Bundle a windowed launcher and a console CLI in one portable directory."""
from importlib.metadata import distribution
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parents[1]
sys.path.insert(0, str(root))
freezer = distribution("pyinstaller")
boot_license = next(f.locate() for f in freezer.files if f.name == "COPYING.txt")
packaging_dir = root / "packaging" / "windows"
analysis = Analysis(
    [str(packaging_dir / "entry.py"), str(packaging_dir / "desktop_entry.py")],
    pathex=[str(root)],
    datas=[
        (str(root / "nuclemu" / "static"), "nuclemu/static"),
        (str(root / "LICENSE"), "licenses/Nuclemu"),
        (str(Path(sys.base_prefix) / "LICENSE.txt"), "licenses/Python"),
        (str(boot_license), "licenses/PyInstaller"),
    ],
    hiddenimports=collect_submodules("nuclemu.experiments"),
)
archive = PYZ(analysis.pure)
# Both programs need the runtime hooks, but each executes only its own entry script.
def program(entry, name, console):
    other_entry = "entry" if entry == "desktop_entry" else "desktop_entry"
    scripts = [script for script in analysis.scripts if script[0] != other_entry]
    return EXE(archive, scripts, [], exclude_binaries=True,
               icon=str(root / "nuclemu" / "static" / "nuclemu.ico"),
               manifest=str(packaging_dir / "nuclemu.manifest"),
               name=name, console=console, upx=False)

cli = program("entry", "nuclemu", console=True)
desktop = program("desktop_entry", "Nuclemu-Desktop", console=False)
COLLECT(cli, desktop, analysis.binaries, analysis.datas, name="Nuclemu", upx=False)
