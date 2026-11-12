"""Validate imported scientific records once, before opening a new live lab."""

from collections.abc import Mapping
from dataclasses import replace
from math import isclose, isfinite
from types import MappingProxyType

from .acquisition import ConfigurationChange, RoundInfo, SettingChange, Snapshot, TargetChange
from .core import Measurement


def _number(value, label, *, positive=False):
    if (type(value) not in (int, float) or not isfinite(value)
            or (value <= 0 if positive else value < 0)):
        raise ValueError(f"Imported {label} must be finite and {'positive' if positive else 'nonnegative'}")
    return value


def _values(values, *, outputs=False):
    if not isinstance(values, Mapping) or any(not isinstance(key, str) or not key for key in values):
        raise ValueError("Imported configuration must be a mapping with named keys")
    if outputs:
        if any(type(value) is not bool for value in values.values()):
            raise ValueError("Imported output switches must be boolean")
    elif any(type(value) not in (int, float) or not isfinite(value) for value in values.values()):
        raise ValueError("Imported settings must be finite numeric values")
    return MappingProxyType(dict(values))


def _positive_int(value, label):
    if type(value) is not int or value <= 0:
        raise ValueError(f"Imported {label} must be a positive integer")


def _changes(items, exposure, start, end, *, outputs=False):
    result = []
    previous_time, previous_exposure = start, 0
    for change in items:
        if not isinstance(change, SettingChange):
            raise ValueError("Imported round changes require SettingChange values")
        t = _number(change.time_s, "change time")
        e = _number(change.exposure_s, "change exposure")
        if not previous_time <= t <= end or not previous_exposure <= e <= exposure:
            raise ValueError("Imported round changes are outside the round timeline")
        result.append(replace(change, values=_values(change.values, outputs=outputs)))
        previous_time, previous_exposure = t, e
    return tuple(result)


def load_history(experiment, time_s, rounds, snapshots, history):
    devices = {d.id: d for d in experiment.devices}
    imported_rounds, by_round = [], {}
    for info in rounds:
        if not isinstance(info, RoundInfo) or info.device not in devices:
            raise ValueError("Imported round belongs to an unknown instrument")
        _positive_int(info.acquisition, "round number")
        start = _number(info.start_s, "round start")
        end = time_s if info.end_s is None else _number(info.end_s, "round end")
        exposure = _number(info.exposure_s, "round exposure")
        if not start <= end <= time_s or exposure > end - start + 1e-9:
            raise ValueError("Imported round exposure is outside its laboratory interval")
        if info.duration_s is not None:
            _number(info.duration_s, "duration", positive=True)
        if info.count_limit is not None:
            _positive_int(info.count_limit, "count limit")
        _number(info.window_s, "statistical window", positive=True)
        if info.initial_duration_s is not None:
            _number(info.initial_duration_s, "initial duration", positive=True)
        if info.initial_count_limit is not None:
            _positive_int(info.initial_count_limit, "initial count limit")
        target_changes = []
        previous_t, previous_e = start, 0
        for change in info.target_changes:
            if not isinstance(change, TargetChange):
                raise ValueError("Imported targets require TargetChange values")
            t = _number(change.time_s, "target change time")
            e = _number(change.exposure_s, "target change exposure")
            if not previous_t <= t <= time_s or not previous_e <= e <= exposure:
                raise ValueError("Imported target changes are outside the round timeline")
            if change.duration_s is not None:
                _number(change.duration_s, "changed duration", positive=True)
            if change.count_limit is not None:
                _positive_int(change.count_limit, "changed count limit")
            target_changes.append(change)
            previous_t, previous_e = t, e
        key = info.device, info.acquisition
        if key in by_round:
            raise ValueError("Duplicate imported instrument round")
        copied = replace(info, initial_settings=_values(info.initial_settings),
                         initial_outputs=_values(info.initial_outputs, outputs=True),
                         changes=_changes(info.changes, exposure, start, time_s),
                         output_changes=_changes(info.output_changes, exposure, start, time_s, outputs=True),
                         target_changes=tuple(target_changes))
        imported_rounds.append(copied)
        by_round[key] = copied

    imported_snapshots, ids = [], set()
    for item in snapshots:
        if not isinstance(item, Snapshot) or item.device not in devices:
            raise ValueError("Imported snapshot belongs to an unknown instrument")
        _positive_int(item.id, "snapshot id")
        if item.id in ids:
            raise ValueError("Duplicate imported snapshot id")
        ids.add(item.id)
        info = by_round.get((item.device, item.acquisition))
        if info is None:
            raise ValueError("Imported snapshot has no matching instrument round")
        _number(item.exposure_s, "snapshot exposure", positive=True)
        _number(item.time_s, "snapshot time")
        if item.time_s > time_s or item.exposure_s > info.exposure_s + 1e-9:
            raise ValueError("Imported snapshot exceeds the saved round")
        channels = devices[item.device].channels
        if len(item.counts) != channels or any(type(v) is not int or v < 0 for v in item.counts):
            raise ValueError("Imported snapshot has invalid cumulative counts")
        totals, exposure, previous = [0] * channels, 0, info.start_s
        segments = []
        for row in item.segments:
            if (not isinstance(row, Measurement) or row.acquisition != item.acquisition
                    or row.readings.keys() != {item.device}):
                raise ValueError("Imported snapshot segment has the wrong instrument or round")
            start, end = _number(row.start_s, "segment start"), _number(row.end_s, "segment end")
            if not previous <= start < end <= item.time_s:
                raise ValueError("Imported snapshot segments overlap or exceed the capture time")
            values = tuple(row.readings[item.device])
            if len(values) != channels or any(type(v) is not int or v < 0 for v in values):
                raise ValueError("Imported snapshot has invalid channel counts")
            totals = [a + b for a, b in zip(totals, values)]
            exposure += end - start
            previous = end
            segments.append(Measurement(start, end, _values(row.settings),
                                        MappingProxyType({item.device: values}), row.acquisition))
        if tuple(totals) != tuple(item.counts) or not isclose(exposure, item.exposure_s, rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError("Imported snapshot totals or exposure do not match its segments")
        imported_snapshots.append(replace(item, counts=tuple(totals), segments=tuple(segments)))

    imported_history, last_time = [], 0
    for index, change in enumerate(history, 1):
        if (not isinstance(change, ConfigurationChange) or type(change.sequence) is not int
                or change.sequence != index or change.kind not in ("settings", "output")):
            raise ValueError("Imported configuration history has an invalid sequence or kind")
        t = _number(change.time_s, "configuration time")
        if not last_time <= t <= time_s:
            raise ValueError("Imported configuration history is outside the laboratory timeline")
        imported_history.append(replace(change, values=_values(change.values, outputs=change.kind == "output")))
        last_time = t
    return imported_rounds, imported_snapshots, imported_history
