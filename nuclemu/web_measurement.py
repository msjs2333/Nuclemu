"""Explicit, side-effect-free file inspection followed by targeted loading."""

from uuid import uuid4

from .exchange import decode_measurement, load_item, load_package


def inspect_measurement(lab, device, raw=None):
    if lab.readonly or not lab.work.session.experiment.outputs:
        raise ValueError('请在可继续采集的实验中载入测量数据。')
    if device not in lab.analysis:
        raise ValueError('请选择有效的仪器或窗。')
    if lab.exchange.document is not None:
        lab.work.bind_source(lab.exchange.document['id'])
    source = lab.exchange.document if raw is None else (
        load_package(raw) if raw.startswith((b'PK', b'SQLite format 3')) else load_item(raw))
    if source is None:
        raise ValueError('本场还没有可载入的测量记录。')
    choices = [dict(id=item['id'], title=item['title'], exposure_s=item['document']['snapshot']['exposure_s'])
               for item in source['items'] if item['kind'] == 'measurement'
               and item['document']['snapshot']['device'] == device]
    if not choices:
        raise ValueError('文件中没有适用于所选仪器或窗的测量记录。')
    token = uuid4().hex
    target = lab.work.session.instrument(device)
    lab._pending_measurement = token, device, source, target.acquisition
    return dict(token=token, device=device, items=choices,
                overwrite_required=target.exposure_s > 0 or any(target.counts))


def load_measurement(lab, token, identity, overwrite=False):
    pending = getattr(lab, '_pending_measurement', None)
    if pending is None or token != pending[0]:
        raise ValueError('载入选择已过期，请重新选择测量记录。')
    _, device, source, acquisition = pending
    if lab.work.session.instrument(device).acquisition != acquisition:
        raise ValueError('目标仪器的测量轮次已改变，请重新选择测量记录并确认载入。')
    decoded = decode_measurement(source, lab.work.session.experiment, device, identity)
    lab.work.session.load_measurement(device, decoded.snapshot, overwrite=overwrite)
    if decoded.calibration is None:
        lab.work.lab.calibrations.pop(device, None)
    else:
        lab.work.lab.calibrations[device] = decoded.calibration
    lab._live_calibrations[device] = decoded.calibration
    lab._saved_calibration_devices.discard(device)
    lab.clear_portable_reference(device, 'selected')
    lab.analysis[device]['selected'] = None
    if lab.work.device.id == device:
        lab.work.select(None)
    del lab._pending_measurement
    lab.edits += 1
