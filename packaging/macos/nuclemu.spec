"""Native-architecture app with a bundled console companion and Tcl/Tk."""
from importlib.metadata import distribution
from pathlib import Path
import os
import sys
import tomllib

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parents[1]
sys.path.insert(0, str(root))
version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
freezer = distribution('pyinstaller')
boot_license = next(f.locate() for f in freezer.files if f.name == 'COPYING.txt')
folder = root / 'packaging' / 'macos'
import sysconfig
python_license = next(path for path in (
    Path(sys.base_prefix) / 'LICENSE.txt',
    Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt',
    Path(sys.base_prefix) / 'Resources' / 'English.lproj' / 'License.rtf',
    Path(sys.base_prefix) / 'Resources' / 'Python.app' / 'Contents' / 'Resources' / 'English.lproj' / 'License.rtf',
) if path.is_file())
analysis = Analysis([str(folder / 'desktop_entry.py'), str(folder / 'entry.py')],
    pathex=[str(root)],
    datas=[(str(root / 'nuclemu' / 'static'), 'nuclemu/static'),
           (str(root / 'LICENSE'), 'licenses/Nuclemu'),
           (str(python_license), 'licenses/Python'),
           (str(boot_license), 'licenses/PyInstaller'),
           (str(folder / 'README.md'), 'macOS-README')],
    hiddenimports=collect_submodules('nuclemu.experiments'))
archive = PYZ(analysis.pure)

def program(entry, name, console):
    other = 'entry' if entry == 'desktop_entry' else 'desktop_entry'
    scripts = [script for script in analysis.scripts if script[0] != other]
    return EXE(archive, scripts, [], name=name, exclude_binaries=True,
        console=console, upx=False, argv_emulation=False,
        target_arch=os.environ['NUCLEMU_MAC_ARCH'])

desktop = program('desktop_entry', 'Nuclemu', False)
cli = program('entry', 'nuclemu-cli', True)
collection = COLLECT(desktop, cli, analysis.binaries, analysis.datas,
                     name='Nuclemu', upx=False)
BUNDLE(collection, name='Nuclemu.app', bundle_identifier='org.nuclemu.desktop',
    icon=os.environ.get('NUCLEMU_MAC_ICON'),
    info_plist=dict(CFBundleName='Nuclemu', CFBundleDisplayName='Nuclemu',
        CFBundleShortVersionString=version, CFBundleVersion='2',
        NSHighResolutionCapable=True, LSMinimumSystemVersion='11.0',
        NSHumanReadableCopyright='Nuclemu contributors. See bundled licenses.'))
