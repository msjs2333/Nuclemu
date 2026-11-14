"""Explicit spectrum analysis with a fixed observation and calibration."""

from uuid import uuid4

from .results import roi_centroid


def roi_context(lab):
    """Identify the selected spectrum without tying a request to each new count."""
    work = lab.work
    if work.device.kind != 'spectrum':
        return None
    identity = lab.saved_selection.get(work.device.id, {}).get('selected')
    index = work.lab.selected
    if identity:
        acquisition = lab.saved_measurement(identity).snapshot.acquisition
    elif work.session.experiment.outputs and not lab.readonly and index is None:
        acquisition = work.session.instrument(work.device.id).acquisition
    else:
        segment = work.segment()
        acquisition = segment.get('acquisition') if segment else None
    return dict(device=work.device.id, record_id=identity, segment_index=index,
                acquisition=acquisition)


def _observation(lab):
    work = lab.work
    identity = lab.saved_selection.get(work.device.id, {}).get('selected')
    if identity:
        snapshot = lab.saved_measurement(identity).snapshot
        return snapshot.counts, snapshot.exposure_s, snapshot.time_s
    if work.session.experiment.outputs and not lab.readonly and work.lab.selected is None:
        instrument = work.session.instrument(work.device.id)
        return instrument.counts, instrument.readable_exposure_s, work.session.time_s
    segment = work.segment()
    if segment is None:
        return (0,) * work.device.channels, 0.0, lab.time_s()
    return (segment['readings'][work.device.id],
            segment['end_s'] - segment['start_s'], segment['end_s'])


def spectrum_readout(lab):
    """Live totals only: polling never calculates a new ROI result."""
    counts, exposure, _ = _observation(lab)
    if exposure == 0:
        return None
    total = sum(counts)
    return dict(counts=total, exposure_s=exposure, rate=total / exposure)


def calculate_roi(lab, data):
    """Capture one count-weighted ROI result only after an explicit command."""
    lab._check_device_target(data)
    context = roi_context(lab)
    if context is None:
        raise ValueError('只有谱仪可以计算 ROI 重心。')
    if data.get('roi_context') != context:
        raise ValueError('所选谱或采集轮次已改变，请重新查看谱后计算 ROI 重心。')
    bounds = data.get('roi')
    if (not isinstance(bounds, list) or len(bounds) != 2
            or any(type(channel) is not int for channel in bounds)
            or not 0 <= bounds[0] <= bounds[1] < lab.work.device.channels):
        raise ValueError('ROI 必须位于当前仪器的有效道址内。')
    counts, exposure, time_s = _observation(lab)
    counts = tuple(counts)
    first, last = bounds
    center = roi_centroid(counts, first, last)
    calibration = lab.selected_calibration()
    total = sum(counts)
    readout = dict(counts=total, exposure_s=exposure, rate=total / exposure if exposure else None,
                   roi_counts=sum(counts[first:last + 1]), centroid=center,
                   energy_MeV=calibration.energy(center) if calibration and center is not None else None)
    result = dict(id=uuid4().hex, **context, roi=tuple(bounds), counts=counts,
                  exposure_s=exposure, time_s=time_s,
                  calibration=calibration.document() if calibration else None, readout=readout)
    lab.analysis[lab.work.device.id]['roi'] = list(bounds)
    lab._roi_results[lab.work.device.id] = result
    lab.edits += 1
