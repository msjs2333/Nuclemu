"""Build an offline Debian package and a relocatable directory archive on Linux."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import tomllib


def run(*args):
    subprocess.run(args, check=True)


def write(path, text, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    path.chmod(mode)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--revision', default='1', help='Debian candidate revision')
    parser.add_argument('--output', type=Path, default=Path('dist/release'))
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        parser.error('Build on Linux x86_64')
    if not args.revision.isdigit():
        parser.error('revision must be numeric')
    root = Path(__file__).resolve().parents[2]
    os.chdir(root)
    version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
    if version != '0.0.1':
        raise ValueError('This release recipe targets 0.0.1')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work = root / 'build/linux' / ('candidate-' + args.revision)
    if work.exists():
        raise FileExistsError(f'Use a fresh build directory: {work}')
    run('python', '-m', 'PyInstaller', '--clean', '--noconfirm',
        '--workpath', str(work / 'freeze'), '--distpath', str(work / 'bundle'),
        str(root / 'packaging/linux/nuclemu.spec'))
    bundle = work / 'bundle/Nuclemu'
    write(bundle / 'nuclemu-desktop', '#!/bin/sh\nAPP=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec "$APP/nuclemu" serve --gui "$@"\n', 0o755)
    # Resolve only shipped shared libraries to their Debian package notices.
    notices = bundle / 'licenses/Debian-notices'
    packages = set()
    for library in bundle.rglob('*.so*'):
        if not library.is_file():
            continue
        owners = subprocess.check_output(['dpkg-query', '-S', '*/' + library.name], text=True)
        for line in owners.splitlines():
            package = line.split(': ', 1)[0].split(':', 1)[0]
            packages.add(package)
    common_licenses = set()
    for package in sorted(packages):
        copyright_file = Path('/usr/share/doc') / package / 'copyright'
        destination = notices / package / 'copyright'
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(copyright_file, destination)
        common_licenses.update(re.findall(r'/usr/share/common-licenses/([A-Za-z0-9.+-]+)', copyright_file.read_text()))
    for name in sorted(common_licenses):
        source_license = Path('/usr/share/common-licenses') / name
        if source_license.is_file():
            destination = bundle / 'licenses/common-licenses' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_license, destination)
    write(bundle / 'licenses/Debian-packages.json', json.dumps(sorted(packages), indent=2) + '\n')
    try:
        source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        source = os.environ.get('NUCLEMU_SOURCE_SHA')
    if not source:
        raise ValueError('Provide NUCLEMU_SOURCE_SHA when Git metadata is unavailable')
    metadata = dict(version=version, debian_version=f'{version}-{args.revision}', source_sha=source,
                    architecture='amd64', baseline='Debian 12 / glibc 2.36',
                    python=platform.python_version(), libc=platform.libc_ver())
    write(bundle / 'BUILD-INFO.json', json.dumps(metadata, indent=2) + '\n')
    shutil.copy2(root / 'packaging/linux/README.md', bundle / 'README.md')
    stage = work / 'deb'
    shutil.copytree(bundle, stage / 'opt/nuclemu')
    for command in ('nuclemu', 'nuclemu-desktop'):
        write(stage / 'usr/bin' / command, f'#!/bin/sh\nexec /opt/nuclemu/{command} "$@"\n', 0o755)
    write(stage / 'usr/share/applications/nuclemu.desktop',
        '[Desktop Entry]\nType=Application\nName=Nuclemu\nComment=A Virtual Nuclear Physics Lab\n'
        'Exec=nuclemu-desktop\nTryExec=nuclemu-desktop\nIcon=nuclemu\nTerminal=false\nCategories=Education;Science;Physics;\n')
    icon = stage / 'usr/share/pixmaps/nuclemu.png'
    icon.parent.mkdir(parents=True)
    shutil.copy2(root / 'nuclemu/static/nuclemu-mark.png', icon)
    write(stage / 'usr/share/doc/nuclemu/copyright', (root / 'LICENSE').read_text())
    size = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file()) // 1024
    write(stage / 'DEBIAN/control', f'Package: nuclemu\nVersion: {version}-{args.revision}\n'
        f'Architecture: amd64\nMaintainer: Nuclemu contributors\nInstalled-Size: {size}\n'
        'Section: education\nPriority: optional\n'
        'Depends: libc6 (>= 2.36), libx11-6, libxext6, libxft2, libxrender1, libfontconfig1, libfreetype6, libexpat1, zlib1g\n'
        'Recommends: xdg-utils, fonts-noto-cjk\n'
        'Description: A Virtual Nuclear Physics Lab\n Offline laboratory workbench with bundled Python and Tk runtime.\n')
    deb = output / f'nuclemu_{version}-{args.revision}_amd64.deb'
    run('dpkg-deb', '--root-owner-group', '--build', str(stage), str(deb))
    portable = output / f'nuclemu-{version}-{args.revision}-linux-amd64.tar.gz'
    with tarfile.open(portable, 'w:gz') as archive:
        archive.add(bundle, arcname=f'nuclemu-{version}')
    for artifact in (deb, portable):
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        write(artifact.with_name(artifact.name + '.sha256'), f'{digest}  {artifact.name}\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
