"""Exercise installed or relocated binaries against cross-platform sample files."""
import argparse
import base64
import json
from pathlib import Path
import re
import selectors
import signal
import socket
import subprocess
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cli', required=True, type=Path)
    parser.add_argument('--samples', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    cli = str(args.cli.resolve())
    args.output.mkdir(parents=True, exist_ok=False)

    def invoke(*arguments):
        result = subprocess.run([cli, *map(str, arguments)], cwd=args.output,
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout

    invoke('validate')
    process = subprocess.Popen([cli, 'serve', '--no-gui'], cwd=args.output,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            if not selector.select(20):
                raise AssertionError('No ready URL')
            line = process.stdout.readline()
        match = re.search(r'http://127\.0\.0\.1:(\d+)/', line)
        if match is None:
            raise AssertionError(line + process.stderr.read())
        url, port = match[0], int(match[1])

        def post(route, **data):
            request = Request(url + 'api/' + route, json.dumps(data).encode(),
                              {'Content-Type': 'application/json'})
            with urlopen(request, timeout=10) as response:
                return json.load(response)

        with urlopen(url + 'api/catalog', timeout=10) as response:
            catalog = json.load(response)
        assert {r['id'] for r in catalog['experiments']} == {'alpha', 'beta'}
        with urlopen(url, timeout=10) as response:
            html = response.read().decode()
        assets = set(re.findall(r'(?:href|src)="(/[^"]+)"', html))
        assets.update(('/draw.js', '/cover-beta-absorption.webp', '/lab-sans.woff'))
        for asset in assets:
            with urlopen(url.rstrip('/') + asset, timeout=10) as response:
                assert response.read(), asset
        measurements = {}
        for sample in ('AEL', 'BABS'):
            source = args.samples / (sample + '.nuclemu')
            listing = json.loads(invoke('files', 'inspect', source))
            record = next(r for r in listing['records'] if r['kind'] == 'measurement')
            exported = args.output / (sample + '.json')
            invoke('files', 'export', source, '--item', record['id'], '--output', exported)
            bundle = json.loads(exported.read_text())
            products = [r['document'] for r in bundle['items'] if r['kind'] == 'measurement']
            state = post('open_package', file=base64.b64encode(source.read_bytes()).decode())
            session = state['id']
            assert state['portable_loaded']
            for product in products:
                device = product['snapshot']['device']
                member = next(r for r in record.get('measurements', [record]) if r.get('device') == device)
                post('action', session=session, action='device', device=device)
                selected = post('action', session=session, action='select', device=device, item_id=member['id'])
                channels = len(selected['selected_observation']['counts'])
                expected = [sum(w['counts'][i] for w in product['windows']) for i in range(channels)]
                assert selected['selected_observation']['counts'] == expected
                assert selected['selected_observation']['exposure_s'] == product['snapshot']['exposure_s']
                if sample == 'AEL':
                    calibration = next(r['document'] for r in bundle['items'] if r['kind'] == 'calibration')
                    for key in ('channel1', 'energy1', 'channel2', 'energy2'):
                        assert selected['calibration'][key] == calibration[key]
            if sample == 'BABS':
                by_device = {p['snapshot']['device']: p for p in products}
                assert len(by_device['counter']['windows']) == 3
                assert all(w['complete'] for w in by_device['counter']['windows'])
                assert len(by_device['counter_b']['windows']) == 1
                assert not by_device['counter_b']['windows'][0]['complete']
            # Re-export all items through this binary's service and reopen with CLI.
            request = Request(url + 'api/download', json.dumps(dict(session=session, scope='experiment')).encode(),
                              {'Content-Type': 'application/json'})
            copied = args.output / (sample + '.nuclemu')
            with urlopen(request, timeout=10) as response:
                copied.write_bytes(response.read())
            copied_listing = json.loads(invoke('files', 'inspect', copied))
            assert copied_listing['items'] == listing['items']
            copied_json = args.output / (sample + '-reopened.json')
            invoke('files', 'export', copied, '--item', record['id'], '--output', copied_json)
            assert json.loads(copied_json.read_text())['items'] == bundle['items']
            measurements[sample] = [dict(device=p['snapshot']['device'],
                exposure_s=p['snapshot']['exposure_s'], counts=sum(sum(w['counts']) for w in p['windows'])) for p in products]
            token = post('action', session=session, action='freeze')['confirmation_id']
            post('action', session=session, action='discard', confirmation_id=token)
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, (process.returncode, stderr)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', port))
        report = dict(passed=True, cli=cli, samples=measurements, assets=len(assets),
                      interrupt_exit=process.returncode, port_rebound=port)
        (args.output / 'report.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


if __name__ == '__main__':
    main()
