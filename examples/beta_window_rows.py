"""Five short windows, one long window and live foil changes in one round.

Run ``python -m examples.beta_window_rows`` for the actual rows, or add
``--directory PATH`` to write the explicit snapshots and portable files.
"""

import argparse
from decimal import Decimal
import json
from pathlib import Path

from nuclemu.core import Session
from nuclemu.experiments.beta import DETECTOR_OUTPUT, EXPERIMENT


def window_document(window):
    """JSON view of the public immutable window; keep every condition part."""
    return dict(device=window.device, number=window.number, acquisition=window.acquisition,
                start_exposure_s=window.start_exposure_s,
                end_exposure_s=window.end_exposure_s,
                exposure_s=window.end_exposure_s - window.start_exposure_s,
                counts=list(window.counts), complete=window.complete, window_s=window.window_s,
                parts=[dict(start_s=p.start_s, end_s=p.end_s, exposure_s=p.exposure_s,
                            settings=dict(p.settings),
                            readings={d: list(v) for d, v in p.readings.items()})
                       for p in window.parts])


def acquire(*, seed=42, hot_change=True, retime=False, pause=False, chunks=None):
    """A=1s, B=5s, source present, optional change at 2.5s.

    ``retime`` requests A=2s while its third 1s window is open. It takes
    effect at the next A boundary, leaving B untouched. Caller-supplied
    chunks can exercise display polling without moving any operation time.
    """
    session = Session(EXPERIMENT, seed=seed)
    session.configure({'source_present': 1, 'foil_count': 0, 'foil_spec_um': 100})
    session.set_output(DETECTOR_OUTPUT, True)
    session.configure_acquisition('counter', duration_s=5, window_s=1)
    session.configure_acquisition('counter_b', duration_s=5, window_s=5)
    group = next(p.devices for p in EXPERIMENT.components if p.id == 'counter')
    session.start_group(group)
    def advance(duration):
        if chunks is None:
            session.advance(duration)
        else:
            remaining = Decimal(str(duration))
            while remaining:
                step = min(Decimal(str(chunks)), remaining)
                session.advance(float(step))
                # Read-only consumers must not change measurement boundaries.
                session.instrument_windows('counter')
                session.particle_flow
                remaining -= step
    advance(2.5)
    if hot_change:
        session.set('foil_count', 4)
    if retime:
        session.configure_acquisition('counter', window_s=2)
    if pause:
        advance(.5)
        session.stop_group(group)
        advance(7)
        session.start_group(group)
        advance(2)
    else:
        advance(2.5)
    session.snapshot('counter')
    session.snapshot('counter_b')
    session.set_output(DETECTOR_OUTPUT, False)
    return session


def pause_resume(*, seed=42):
    """One counter-wide pause/resume retains two separate exposure clocks."""
    session = Session(EXPERIMENT, seed=seed)
    session.set('source_present', 1)
    session.set_output(DETECTOR_OUTPUT, True)
    group = next(p.devices for p in EXPERIMENT.components if p.id == 'counter')
    session.configure_acquisition('counter', window_s=1)
    session.configure_acquisition('counter_b', window_s=5)
    session.start_group(group)
    session.advance(3)
    session.snapshot('counter')
    session.snapshot('counter_b')
    session.stop_group(group)
    session.advance(7)  # Detector remains on, but neither gate accumulates.
    session.start_group(group)
    session.advance(2)
    session.stop_group(group)
    return session


def rows(session):
    return {d: [window_document(w) for w in session.instrument_windows(d)]
            for d in ('counter', 'counter_b')}


def write_files(session, directory):
    from nuclemu.exchange import capture_session, export_item, load_item, load_package, save_package
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    document = capture_session(session)
    path = directory / 'beta-windows.nuclemu'
    save_package(path, document)
    loaded = load_package(path)
    for item in loaded['items']:
        device = item['document']['snapshot']['device']
        assert len(item['document']['windows']) == len(session.instrument_windows(device))
        for fmt in ('json', 'csv'):
            data = export_item(loaded, item['id'], fmt)
            output = directory / f'{device}.{fmt}'
            output.write_bytes(data)
            restored = load_item(output)
            assert restored['items'][0]['document'] == item['document']
    (directory / 'window-rows.json').write_text(
        json.dumps(rows(session), ensure_ascii=False, indent=2), encoding='utf-8')
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory')
    parser.add_argument('--retime', action='store_true')
    parser.add_argument('--pause', action='store_true', help='pause both at 3 s, wait 7 s, then continue 2 s')
    args = parser.parse_args()
    session = acquire(retime=args.retime, pause=args.pause)
    if args.directory:
        print(write_files(session, args.directory))
    print(json.dumps(rows(session), ensure_ascii=True, indent=2))
