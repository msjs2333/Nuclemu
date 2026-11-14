"""Whole-instrument actions over existing cached measurement items."""

from copy import deepcopy
from uuid import uuid4

from .exchange import (bind_calibration, capture_session, link_measurements,
                       native_snapshot_id, rename_record, validate_record_name)
from .web_exchange import WebExchange


def members(lab, component):
    part = next((p for p in lab.info['components']
                 if p['id'] == component and p['kind'] == 'instrument'), None)
    devices = (part.get('devices') or ([part['device']] if part.get('device') else [])) if part else ()
    if not devices or lab.work.device.id not in devices:
        raise ValueError('所用仪器已改变，请重新查看仪器后操作。')
    return tuple(devices)


def validate_action(lab, data):
    """Reject a stale naming or clear dialog before settling the clock."""
    devices = members(lab, data['component'])
    if data['action'] != 'finish_clear_group':
        lab._check_device_target(data)
    if data['action'] == 'snapshot_group':
        acquisitions = data.get('acquisitions')
        if (not isinstance(acquisitions, dict) or set(acquisitions) != set(devices)
                or any(acquisitions[d] != lab.work.session.instrument(d).acquisition
                       or (acquisitions[d] is not None and type(acquisitions[d]) is not int)
                       for d in devices)):
            raise ValueError('测量轮次已改变，请重新命名并保存。')
        validate_record_name(data.get('title'))
    elif data['action'] == 'finish_clear_group':
        pending = getattr(lab, '_group_clear', None)
        if not pending or pending['component'] != data['component'] or pending['token'] != data.get('token'):
            raise ValueError('清空确认已过期，请重新操作。')
        if data.get('choice') == 'save':
            validate_record_name(data.get('title'))
    return devices


def stage_writer(lab, devices, title, staged, *, calibrations=None, calibration_items=None):
    def write(snapshots):
        try:
            if lab.cache_writer is not None:
                for snapshot in snapshots:
                    lab.cache_writer(snapshot)
            doc = capture_session(lab.work.session, lab.exchange.document,
                                  definition=lab.info, device=lab.work.device.id,
                                  additional_snapshots=snapshots)
            exchange = WebExchange(doc)
            doc = exchange.refresh(lab.work.session, device=lab.work.device.id,
                definition=lab.info, product=lab.work.product(), analysis=lab.analysis,
                item_indices=getattr(lab.work.lab.view, 'item_indices', None),
                preserved_analysis=getattr(lab, 'portable_preserved_analysis', None),
                identity_analysis=lab.saved_analysis)
            identities = [native_snapshot_id(doc, s) for s in snapshots]
            if len(devices) > 1:
                link_measurements(doc, identities, title, members=devices)
            else:
                rename_record(doc, identities[0], title)
            for snapshot in snapshots:
                calibration = (calibrations.get(snapshot.device) if calibrations is not None else
                    lab._live_calibrations.get(snapshot.device)
                    if snapshot.device in lab._saved_calibration_devices
                    else lab.work.lab.calibrations.get(snapshot.device))
                if calibration is None or not all(calibration.applies_to(s.settings) for s in snapshot.segments):
                    continue
                candidates = [i for i in reversed(doc['items']) if i['kind'] == 'calibration'
                              and i['document'] == calibration.document()]
                loaded = lab._loaded_calibration_items if calibration_items is None else calibration_items
                saved = next((i for i in candidates if i['id'] == loaded.get(snapshot.device)),
                             next(iter(candidates), None))
                if saved:
                    bind_calibration(doc, native_snapshot_id(doc, snapshot), saved['id'])
            staged.append(doc)
        finally:
            lab.sync()
    return write


def act(lab, data):
    devices = members(lab, data['component'])
    session = lab.work.session
    action = data['action']
    if action == 'begin_clear_group':
        if getattr(lab, '_group_clear', None):
            raise ValueError('请先完成当前清空确认。')
        requests = session.begin_clear_group(devices)
        if not any(r.snapshot is not None for r in requests):
            session.finish_clear_group(devices, {r.device: r.token for r in requests}, 'discard')
        else:
            lab._group_clear = dict(component=data['component'], token=uuid4().hex,
                devices=list(devices), exposures={r.device: r.snapshot.exposure_s if r.snapshot else 0 for r in requests},
                requests=requests)
        return
    staged = []
    if action == 'snapshot_group':
        session.snapshot_group(devices, writer=stage_writer(lab, devices, data['title'], staged))
    else:
        pending = lab._group_clear
        try:
            session.finish_clear_group(devices, {r.device: r.token for r in pending['requests']},
                data['choice'], writer=stage_writer(lab, devices, data.get('title'), staged))
        finally:
            if all(session.pending_clear(d) is None for d in devices):
                lab._group_clear = None
    if staged:
        lab.exchange.document = staged[0]
        lab.work.bind_source(staged[0]['id'])
        lab._decoded_items.clear()
    lab.edits += 1


def rename(lab, identity, title):
    validate_record_name(title)
    if lab.exchange.document is None:
        raise ValueError('请选择已保存的记录。')
    doc = deepcopy(lab.exchange.document)
    rename_record(doc, identity, title)
    lab.exchange.document = doc
    lab._decoded_items.clear()
    lab._imported_count = 0
    lab._imported_items = []
    lab.edits += 1
