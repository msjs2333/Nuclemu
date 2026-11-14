"""Build the portable Windows CLI and browser workbench from the repository."""
from importlib.metadata import distribution
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parents[1]
sys.path.insert(0, str(root))
freezer = distribution("pyinstaller")
boot_license = next(f.locate() for f in freezer.files if f.name == "COPYING.txt")
analysis = Analysis(
    [str(root / "packaging" / "windows" / "entry.py")],
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
executable = EXE(archive, analysis.scripts, [], exclude_binaries=True,
                 name="nuclemu", console=True, upx=False)
COLLECT(executable, analysis.binaries, analysis.datas, name="Nuclemu", upx=False)
