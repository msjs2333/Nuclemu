"""Exercise DMG install/revision replacement/removal using only the frozen CLI.

The driver uses the runner's Python standard library. The installed application's
commands run with a minimal PATH, isolated HOME and no host Python variables.
No downloads, pip, source imports or graphical session are used by this smoke.
"""
import argparse
from base64 import b64encode
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import platform
import plistlib
from queue import Queue
import re
import shutil
import signal
import socket
import subprocess
import os
import sys
from threading import Thread
from time import monotonic
from urllib.request import Request, urlopen


def run(*args, **kwargs):
    return subprocess.check_output([str(arg) for arg in args], text=True, **kwargs)


@contextmanager
def mounted(dmg, mount):
    mount.mkdir()
    run('/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', mount, dmg)
    try:
        yield mount
    finally:
        run('/usr/bin/hdiutil', 'detach', mount)


def post(url, route, data):
    request = Request(url + route, json.dumps(data).encode(), {'Content-Type': 'application/json'})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def exercise(app, output, home):
    cli = app / 'Contents/MacOS/nuclemu-cli'
    env = {key: value for key, value in os.environ.items()
           if key not in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'TCL_LIBRARY', 'TK_LIBRARY')
           and not key.startswith('DYLD_')}
    env.update(HOME=str(home), PATH='/usr/bin:/bin', PYTHONIOENCODING='utf-8')
    output.mkdir(parents=True)
    def command(*args):
        return run(cli, *args, cwd=output, env=env)
    runtime = json.loads(command('--bundle-check'))
    assert runtime['architecture'] == platform.machine(), runtime
    assert runtime['tcl'] and runtime['tk'], runtime
    assert runtime['resources_present'], runtime
    command('validate')
    calibration = dict(format='nuclemu.calibration/1', unit='MeV', experiment='alpha',
        device='mca', channels=1024, channel1=0, energy1=0, channel2=1000, energy2=6)
    (output / 'calibration.json').write_text(json.dumps(calibration))
    command('run', 'alpha', '--set', 'source_present=1', '--enable-output', 'alpha_detector',
        '--seed', '187', '--duration', '3', '--calibration', 'calibration.json', '--package', 'AEL.nuclemu')
    command('run', 'beta', '--set', 'source_present=1', '--enable-output', 'beta_detector',
        '--seed', '187', '--window', 'counter=1', '--window', 'counter_b=5',
        '--duration', '3', '--package', 'BABS.nuclemu')
    process = subprocess.Popen([str(cli), 'serve', '--no-gui'], cwd=output, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines, logs = Queue(), []
    def read():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)
    Thread(target=read, daemon=True).start()
    port = None
    try:
        deadline = monotonic() + 30
        while True:
            line = lines.get(timeout=max(.01, deadline - monotonic()))
            assert line is not None, logs
            logs.append(line)
            match = re.search(r'http://127\.0\.0\.1:(\d+)/', line)
            if match:
                url, port = match.group(), int(match.group(1))
                break
            assert monotonic() < deadline, logs
        with urlopen(url + 'api/catalog', timeout=10) as response:
            assert {row['id'] for row in json.load(response)['experiments']} == {'alpha', 'beta'}
        with urlopen(url, timeout=10) as response:
            html = response.read().decode()
        assets = set(re.findall(r'(?:href|src)="(/[^"?#]+)', html))
        assets.update(('/draw.js', '/cover-beta-absorption.webp', '/lab-sans.woff', '/vue-LICENSE.txt'))
        for asset in sorted(assets):
            with urlopen(url.rstrip('/') + asset, timeout=10) as response:
                assert response.read(), asset
        readings = {}
        for name in ('AEL', 'BABS'):
            file = output / (name + '.nuclemu')
            inspection = json.loads(command('files', 'inspect', file))
            record = next(row for row in inspection['records'] if row['kind'] == 'measurement')
            command('files', 'export', file, '--item', record['id'], '--output', name + '.json')
            exported = json.loads((output / (name + '.json')).read_text())
            products = [item['document'] for item in exported['items'] if item['kind'] == 'measurement']
            state = post(url, 'api/open_package', dict(file=b64encode(file.read_bytes()).decode()))
            assert state['portable_loaded'] and len(state['saved_measurements']) == len(products)
            if name == 'AEL':
                counts = [sum(window['counts'][i] for window in products[0]['windows']) for i in range(1024)]
                assert state['selected_observation']['counts'] == counts and sum(counts) > 0
                assert state['calibration']['energy2'] == 6
                readings[name] = dict(channels=1024, counts=sum(counts), exposure_s=3, energy2=6)
            else:
                a, b = products
                assert a['snapshot']['device'] == 'counter' and b['snapshot']['device'] == 'counter_b'
                assert a['snapshot']['exposure_s'] == b['snapshot']['exposure_s'] == 3
                assert len(a['windows']) == 3 and len(b['windows']) == 1 and not b['windows'][0]['complete']
                for member, product in zip(record['measurements'], products):
                    post(url, 'api/action', dict(session=state['id'], action='device', device=member['device']))
                    display = post(url, 'api/action', dict(session=state['id'], action='select',
                        device=member['device'], item_id=member['id']))
                    assert display['selected_observation']['counts'][0] == sum(w['counts'][0] for w in product['windows'])
                readings[name] = dict(exposure_s=3, a_windows=3, b_partial_windows=1,
                    counts=[sum(w['counts'][0] for w in p['windows']) for p in products])
            confirmation = post(url, 'api/action', dict(session=state['id'], action='freeze'))
            post(url, 'api/action', dict(session=state['id'], action='discard',
                confirmation_id=confirmation['confirmation_id']))
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        try:
            code = process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise AssertionError('Packaged service did not stop after SIGINT')
        (output / 'service.log').write_text(''.join(logs))
        process.stdout.close()
    assert code == 0, code
    if port:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', port))
    return dict(runtime=runtime, measurements=readings, service_exit=code, port_released=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dmg', required=True, type=Path)
    parser.add_argument('--previous-dmg', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    assert sys.platform == 'darwin', 'Run on native macOS'
    dmg = args.dmg.resolve()
    previous = args.previous_dmg.resolve() if args.previous_dmg else dmg.with_name(dmg.stem + '-r1.dmg')
    assert dmg != previous and previous.is_file()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    home = out / '用户 home'
    settings = home / '.nuclemu' / 'launcher.json'
    settings.parent.mkdir(parents=True)
    settings.write_text('{"port":0,"open_browser":false}\n')
    original_settings = settings.read_bytes()
    target = out / '中文 Applications' / 'Nuclemu.app'
    target.parent.mkdir()
    with mounted(previous, out / 'mount-old') as volume:
        run('/usr/bin/ditto', volume / 'Nuclemu.app', target)
    with (target / 'Contents/Info.plist').open('rb') as stream:
        old_revision = plistlib.load(stream)['CFBundleVersion']
    assert old_revision == '1'
    assert (target / 'Contents/Resources/obsolete-revision-1.txt').is_file()
    old_result = exercise(target, out / 'revision-1', home)
    saved = out / 'student-files'
    saved.mkdir()
    for name in ('AEL.nuclemu', 'BABS.nuclemu'):
        shutil.copy2(out / 'revision-1' / name, saved / name)
    digests = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in saved.iterdir()}
    # macOS drag replacement removes the old bundle; only program files live here.
    shutil.rmtree(target)
    with mounted(dmg, out / 'mount-current') as volume:
        run('/usr/bin/ditto', volume / 'Nuclemu.app', target)
    with (target / 'Contents/Info.plist').open('rb') as stream:
        new_revision = plistlib.load(stream)['CFBundleVersion']
    assert new_revision == '2' and new_revision != old_revision
    assert not (target / 'Contents/Resources/obsolete-revision-1.txt').exists()
    new_result = exercise(target, out / 'revision-2', home)
    cli = target / 'Contents/MacOS/nuclemu-cli'
    for file in saved.iterdir():
        run(cli, 'files', 'inspect', file, cwd=out, env={**os.environ, 'HOME': str(home), 'PATH': '/usr/bin:/bin'})
    assert settings.read_bytes() == original_settings
    shutil.rmtree(target)
    assert not target.exists() and settings.read_bytes() == original_settings
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in saved.iterdir()} == digests
    report = dict(platform=platform.platform(), architecture=platform.machine(),
        install='DMG mounted read-only, app copied to isolated Applications directory',
        upgrade='package revision 1 -> 2; same physics/source version; obsolete resource removed',
        uninstall='app removed; user preferences and saved files retained',
        revisions=[old_revision, new_revision], previous=old_result, current=new_result,
        desktop='pending: Finder, Gatekeeper, window activation, native save dialog',
        network='no downloads during smoke; runner network not globally disabled')
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
