"""Explicit, side-effect-free file inspection followed by targeted loading."""

from uuid import uuid4

from .exchange import (decode_measurement, decode_measurements, load_item, load_package,
                       list_records, capture_session, import_item, measurement_response_context)


def continuation_notice(source, items_by_id, row, current):
    """Describe the selected observations, not their receiving container."""
    identities = set(row.get('group', {}).get('items', [row['id']]))
    devices = {d.id: d for d in current.devices}
    outputs = {o.id: o for o in current.outputs}
    changed, unknown = False, False
    for identity in identities:
        item = items_by_id[identity]
        context = measurement_response_context(item, source['definition'], source.get('id', source.get('package')))
        target = devices[item['document']['snapshot']['device']]
        output = outputs.get(target.input)
        if context is None or not context.get('response'):
            unknown = True
        elif output is None or (context['input'], context['response']) != (target.input, output.response):
            changed = True
    if not (changed or unknown):
        return ''
    reason = ('所选记录的输入或响应版本与当前课程不同。' if changed else '')
    if unknown:
        reason += '所选记录的来源响应不详，不能由当前容器推定。'
    mode = ('独立双窗响应' if current.id == 'beta' and
            len({d.input for d in current.devices}) == 2 else '输入与响应')
    return reason + f'原有计数与实际曝光保留；继续测量使用当前课程的{mode}。'


def inspect_measurement(lab, device, raw=None, *, component=None):
    if lab.readonly or not lab.work.session.experiment.outputs:
        raise ValueError('请在可继续采集的实验中载入测量数据。')
    if component is not None:
        from .web_instrument_records import members
        devices = members(lab, component)
    elif device not in lab.analysis:
        raise ValueError('请选择有效的仪器或窗。')
    else:
        devices = (device,)
    if lab.exchange.document is not None:
        lab.work.bind_source(lab.exchange.document['id'])
    source = lab.exchange.document if raw is None else (
        load_package(raw) if raw.startswith((b'PK', b'SQLite format 3')) else load_item(raw))
    if source is None:
        raise ValueError('本场还没有可载入的测量记录。')
    if component is not None:
        choices = []
        for row in list_records(source):
            if row['kind'] != 'measurement':
                continue
            scope = row.get('group', {}).get('members', [row['device']])
            if ('group' in row and set(scope) != set(devices)) or ('group' not in row and row['device'] not in devices):
                continue
            choices.append(dict(row, devices=list(scope), historical_single='group' not in row and len(devices) > 1,
                exposures={m['device']: m['exposure_s'] for m in row.get('measurements', [row])}))
    else:
        choices = [dict(id=item['id'], title=item['title'], device=device, exposure_s=item['document']['snapshot']['exposure_s'])
                   for item in source['items'] if item['kind'] == 'measurement'
                   and item['document']['snapshot']['device'] == device]
    if not choices:
        raise ValueError('文件中没有适用于所选仪器或窗的测量记录。')
    token = uuid4().hex
    targets = {d: lab.work.session.instrument(d) for d in devices}
    items_by_id = {item['id']: item for item in source['items']}
    for row in choices:
        row['overwrite_required'] = any(targets[d].exposure_s > 0 or any(targets[d].counts)
                                        for d in row.get('devices', (device,)))
        row['notice'] = continuation_notice(source, items_by_id, row, lab.work.session.experiment)
    lab._pending_measurement = dict(token=token, devices=devices, source=source, component=component,
        acquisitions={d: target.acquisition for d, target in targets.items()},
        choices={row['id']: tuple(row.get('devices', (device,))) for row in choices})
    return dict(token=token, device=device, component=component, items=choices,
                notice=choices[0]['notice'],
                overwrite_required=any(t.exposure_s > 0 or any(t.counts) for t in targets.values()))


def load_measurement(lab, token, identity, overwrite=False):
    pending = getattr(lab, '_pending_measurement', None)
    if pending is None or token != pending['token']:
        raise ValueError('载入选择已过期，请重新选择测量记录。')
    devices, source = pending['devices'], pending['source']
    if any(lab.work.session.instrument(d).acquisition != pending['acquisitions'][d] for d in devices):
        raise ValueError('目标仪器的测量轮次已改变，请重新选择测量记录并确认载入。')
    if identity not in pending['choices']:
        raise ValueError('请选择所列的测量记录。')
    if pending['component'] is not None:
        from .web_instrument_records import members
        if members(lab, pending['component']) != devices:
            raise ValueError('目标仪器已改变，请重新选择测量记录。')
        devices = pending['choices'][identity]
        decoded = decode_measurements(source, lab.work.session.experiment, devices, identity)
    else:
        decoded = (decode_measurement(source, lab.work.session.experiment, devices[0], identity),)
    # Prepare calibration imports before changing any gate or live selection.
    doc = capture_session(lab.work.session, lab.exchange.document, definition=lab.info,
                          device=lab.work.device.id)
    retained = {}
    for measurement in decoded:
        item = next(i for i in source['items'] if i['id'] == measurement.item_id)
        calibration_id = item.get('calibration_id')
        if calibration_id is None:
            continue
        calibration = next(i for i in source['items'] if i['id'] == calibration_id)
        existing = next((i['id'] for i in doc['items'] if i['kind'] == 'calibration'
                         and i['source'] == calibration['source'] and i['document'] == calibration['document']), None)
        retained[measurement.snapshot.device] = existing or import_item(doc, source, calibration_id)
    lab.work.session.load_measurements(devices, tuple(d.snapshot for d in decoded), overwrite=overwrite)
    lab.exchange.document = doc
    lab.work.bind_source(doc['id'])
    by_device = {d.snapshot.device: d for d in decoded}
    for device in devices:
        calibration = by_device[device].calibration if device in by_device else None
        if calibration is None:
            lab.work.lab.calibrations.pop(device, None)
        else:
            lab.work.lab.calibrations[device] = calibration
        lab._live_calibrations[device] = calibration
        lab._saved_calibration_devices.discard(device)
        lab._loaded_calibration_items.pop(device, None)
        if device in retained:
            lab._loaded_calibration_items[device] = retained[device]
        lab.clear_portable_reference(device, 'selected')
        lab.analysis[device]['selected'] = None
    if lab.work.device.id in devices:
        lab.work.select(None)
    del lab._pending_measurement
    lab.edits += 1
