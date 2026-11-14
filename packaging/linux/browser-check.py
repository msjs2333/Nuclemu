"""Observe the real default browser opened by the installed desktop entry."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import time
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument('--samples', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir()
settings = Path.home() / '.nuclemu/launcher.json'
settings.parent.mkdir(exist_ok=True)
settings.write_text(json.dumps(dict(port=18862, open_browser=True)))
subprocess.run(['xdg-settings', 'set', 'default-web-browser', 'firefox-esr.desktop'], check=True)
default = subprocess.check_output(['xdg-settings', 'get', 'default-web-browser'], text=True).strip()
assert default == 'firefox-esr.desktop', default
url = 'http://127.0.0.1:18862/'


def post(route, **data):
    request = Request(url + 'api/' + route, json.dumps(data).encode(), {'Content-Type': 'application/json'})
    with urlopen(request, timeout=5) as response:
        return json.load(response)


with (args.output / 'desktop.log').open('w') as log:
    subprocess.run(['gtk-launch', 'nuclemu'], stdout=log, stderr=log, check=True, timeout=10)
    for attempt in range(150):
        try:
            with urlopen(url + 'api/catalog', timeout=.5) as response:
                assert len(json.load(response)['experiments']) == 2
            break
        except OSError:
            time.sleep(.2)
    else:
        raise AssertionError('Menu-launched workbench did not become ready')
    browser = None
    title = None
    for attempt in range(200):
        windows = subprocess.run(['xdotool', 'search', '--onlyvisible', '--class', 'firefox'],
                                 capture_output=True, text=True, timeout=5).stdout.split()
        for window in windows:
            title = subprocess.check_output(['xdotool', 'getwindowname', window], text=True).strip()
            if 'Nuclemu' in title:
                browser = window
                break
        if browser:
            break
        time.sleep(.2)
    assert browser, f'Default Firefox did not display the workbench: {title}'
    time.sleep(2)
    subprocess.run(['scrot', str(args.output / 'default-browser.png')], check=True, timeout=10)
    samples = []
    for name in ('AEL', 'BABS'):
        path = args.samples / (name + '.nuclemu')
        state = post('open_package', file=base64.b64encode(path.read_bytes()).decode())
        assert state['portable_loaded']
        subprocess.run(['xdotool', 'windowactivate', '--sync', browser], check=True, timeout=10)
        subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+r'], check=True, timeout=5)
        time.sleep(1)
        subprocess.run(['scrot', str(args.output / (name + '-browser.png'))], check=True, timeout=10)
        samples.append(dict(sample=name, course=state['definition']['id'], records=len(state['saved_measurements'])))
        token = post('action', session=state['id'], action='freeze')['confirmation_id']
        post('action', session=state['id'], action='discard', confirmation_id=token)
    launcher = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--name', '^Nuclemu$'],
                                       text=True, timeout=5).split()[0]
    subprocess.run(['xdotool', 'windowactivate', '--sync', launcher], check=True, timeout=10)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'alt+F4'], check=True, timeout=5)
    report = dict(passed=True, default_browser=default, browser_title=title, samples=samples,
                  firefox=subprocess.check_output(['firefox-esr', '--version'], text=True).strip())
    (args.output / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
