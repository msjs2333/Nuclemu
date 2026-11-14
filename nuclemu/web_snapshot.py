"""Capture on the save key, then publish that observation after naming."""

from uuid import uuid4

from .exchange import validate_record_name
from .web_instrument_records import members, stage_writer


def validate_action(lab, data):
    """Reject stale pages and names before settling the shared clock."""
    if data['action'] == 'begin_snapshot_group':
        devices = members(lab, data['component'])
        lab._check_device_target(data)
        acquisitions = data.get('acquisitions')
        if (not isinstance(acquisitions, dict) or set(acquisitions) != set(devices)
                or any((acquisitions[d] is not None and type(acquisitions[d]) is not int)
                       or acquisitions[d] != lab.work.session.instrument(d).acquisition for d in devices)):
            raise ValueError('测量轮次已改变，请重新查看仪器后保存。')
    else:
        pending = lab._pending_snapshot
        if not pending or pending['token'] != data.get('token'):
            raise ValueError('保存命名已过期，请重新按保存。')
        if data['action'] == 'commit_snapshot_group':
            validate_record_name(data.get('title'))


def pending_state(lab):
    pending = lab._pending_snapshot
    return (dict(token=pending['token'], component=pending['component'], devices=list(pending['devices']),
                 acquisitions=dict(pending['acquisitions']), exposures=dict(pending['exposures']))
            if pending else None)


def act(lab, data):
    action = data['action']
    if action == 'begin_snapshot_group':
        devices = members(lab, data['component'])
        snapshots = lab.work.session.snapshot_group(devices, cache=False)
        # Capture the applicable calibration as well as counts and exposure.
        # Unsaved calibrations still do not create records implicitly.
        calibrations = {d: (lab._live_calibrations.get(d) if d in lab._saved_calibration_devices
                           else lab.work.lab.calibrations.get(d)) for d in devices}
        by_device = {s.device: s for s in snapshots}
        lab._pending_snapshot = dict(token=uuid4().hex, component=data['component'], devices=devices,
            acquisitions={d: lab.work.session.instrument(d).acquisition for d in devices},
            exposures={d: by_device[d].exposure_s if d in by_device else 0 for d in devices},
            snapshots=snapshots, calibrations=calibrations,
            calibration_items=dict(lab._loaded_calibration_items))
        return
    pending = lab._pending_snapshot
    if action == 'cancel_snapshot_group':
        lab._pending_snapshot = None
        return
    staged = []
    lab.work.session.cache_snapshots(pending['devices'], pending['snapshots'],
        writer=stage_writer(lab, pending['devices'], data['title'], staged,
                            calibrations=pending['calibrations'], calibration_items=pending['calibration_items']))
    lab.exchange.document = staged[0]
    lab.work.bind_source(staged[0]['id'])
    lab._decoded_items.clear()
    lab._pending_snapshot = None
    lab.edits += 1
