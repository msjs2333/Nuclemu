"""Independent interval readouts of shared detector outputs."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from math import isfinite
from types import MappingProxyType

from .core import Measurement, SignalBinding, _UNCHANGED


@dataclass(frozen=True)
class InstrumentState:
    device: str
    running: bool
    acquisition: int | None
    exposure_s: float
    remaining_s: float | None
    cycle: int | None
    counts: tuple[int, ...]
    readable_exposure_s: float
    count_limit: int | None
    duration_s: float | None
    window_s: float
    stop_reason: str | None
    clearing: bool
    next_window_s: float | None = None


@dataclass(frozen=True)
class InstrumentWindow:
    device: str
    number: int
    acquisition: int
    start_exposure_s: float
    end_exposure_s: float
    counts: tuple[int, ...]
    parts: tuple[Measurement, ...]
    complete: bool
    window_s: float | None = None


@dataclass(frozen=True)
class Snapshot:
    id: int
    device: str
    acquisition: int
    time_s: float
    exposure_s: float
    counts: tuple[int, ...]
    segments: tuple[Measurement, ...]
    windows: tuple[InstrumentWindow, ...] = ()
    source: str | None = None
    window_prefix_exposure_s: float = 0
    window_prefix_counts: tuple[int, ...] = ()


@dataclass(frozen=True)
class ClearRequest:
    token: int
    device: str
    acquisition: int | None
    snapshot: Snapshot | None
    was_running: bool


@dataclass(frozen=True)
class SettingChange:
    time_s: float
    exposure_s: float
    values: object


@dataclass(frozen=True)
class ConfigurationChange:
    sequence: int
    time_s: float
    kind: str
    values: object


@dataclass(frozen=True)
class TargetChange:
    time_s: float
    exposure_s: float
    duration_s: float | None
    count_limit: int | None


@dataclass(frozen=True)
class WindowChange:
    time_s: float
    exposure_s: float
    window_s: float
    effective_exposure_s: float


@dataclass(frozen=True)
class RoundInfo:
    device: str
    acquisition: int
    start_s: float
    end_s: float | None
    exposure_s: float
    status: str
    initial_settings: object
    changes: tuple[SettingChange, ...]
    duration_s: float | None
    count_limit: int | None
    window_s: float
    initial_outputs: object
    output_changes: tuple[SettingChange, ...]
    initial_duration_s: float | None = None
    initial_count_limit: int | None = None
    target_changes: tuple[TargetChange, ...] = ()
    random_stream: object = None
    loaded_exposure_s: float = 0
    loaded_source: str | None = None
    initial_window_s: float = 1
    window_changes: tuple[WindowChange, ...] = ()


@dataclass
class _Clear:
    request: ClearRequest
    reason: str | None


@dataclass
class _Gate:
    acquisition: int = 0
    opened: Decimal | None = None
    stop_at: Decimal | None = None
    exposure: Decimal = Decimal(0)
    current: bool = False
    cycle: int = 0
    duration: Decimal | None = None
    count_limit: int | None = None
    window: Decimal = Decimal(1)
    next_check: Decimal = Decimal(1)
    readable_exposure: Decimal = Decimal(0)
    counts: tuple[int, ...] = ()
    segments: list = field(default_factory=list)
    reason: str | None = None
    pending: _Clear | None = None
    started: float = 0
    ended: float | None = None
    initial_settings: object = None
    changes: list = field(default_factory=list)
    initial_outputs: object = None
    output_changes: list = field(default_factory=list)
    initial_duration: float | None = None
    initial_count_limit: int | None = None
    target_changes: list = field(default_factory=list)
    windows: list = field(default_factory=list)
    window_parts: list = field(default_factory=list)
    window_counts: tuple[int, ...] = ()
    window_start: Decimal = Decimal(0)
    pending_window: Decimal | None = None
    loaded_exposure: float = 0
    loaded_source: str | None = None
    window_prefix_exposure: float = 0
    window_prefix_counts: tuple[int, ...] = ()
    initial_window: float = 1
    window_changes: list = field(default_factory=list)


class InstrumentAcquisition:
    """One physical interval is sampled once, then routed to all open gates.

    The fixed one-second physical windows survive display updates. Changes to
    output switches, settings or gates close the pending interval for every
    consumer before applying the operation. There is no per-refresh sampling.
    """

    def __init__(self, session):
        self.session = session
        self.gates = {d.id: _Gate() for d in session.experiment.devices}
        self.enabled = {o.id: False for o in session.experiment.outputs}
        signals = {o.id: SignalBinding(o.id, tuple(d.id for d in session.experiment.devices if d.input == o.id))
                   for o in session.experiment.outputs if any(d.input == o.id for d in session.experiment.devices)}
        self._signals = {d.id: signals[d.input] for d in session.experiment.devices}
        self._output_groups = {key: (key,) for key in self.enabled}
        for part in session.experiment.components:
            if part.outputs:
                self._output_groups.update((key, part.outputs) for key in part.outputs)
        self.begin = session._time
        self.next_window = None
        self.snapshots = []
        self._snapshot_id = 0
        self._clear_token = 0
        self._round_history = []
        self.configuration_history = []
        for device in session.experiment.devices:
            self.gates[device.id].counts = (0,) * device.channels
            self.gates[device.id].window_counts = (0,) * device.channels

    @property
    def running(self):
        return any(g.opened is not None for g in self.gates.values())

    @property
    def clock_running(self):
        return self.running or any(self.enabled.values())

    @property
    def output_enabled(self):
        return MappingProxyType(self.enabled)

    @property
    def active_acquisition(self):
        ids = {g.acquisition for g in self.gates.values() if g.opened is not None}
        return next(iter(ids)) if len(ids) == 1 else None

    @property
    def remaining_s(self):
        open_gates = [g for g in self.gates.values() if g.opened is not None]
        if not open_gates or any(g.stop_at is None for g in open_gates):
            return None
        return float(min(g.stop_at for g in open_gates) - self.session._time)

    def _gate(self, device):
        if device not in self.gates:
            raise ValueError(f"Unknown instrument: {device}")
        return self.gates[device]

    def state(self, device):
        g = self._gate(device)
        elapsed = g.exposure
        if g.opened is not None:
            elapsed += self.session._time - g.opened
        remaining = None if g.duration is None else float(max(Decimal(0), g.duration - elapsed))
        return InstrumentState(device, g.opened is not None,
                               g.acquisition if g.current else None, float(elapsed), remaining,
                               g.cycle if g.opened is not None else None, g.counts,
                               float(g.readable_exposure), g.count_limit,
                               None if g.duration is None else float(g.duration), float(g.window),
                               g.reason, g.pending is not None,
                               None if g.pending_window is None else float(g.pending_window))

    @property
    def rounds(self):
        return tuple(self._round_history) + tuple(
            self._round_info(device, g) for device, g in self.gates.items() if g.current)

    def _round_info(self, device, g, *, cleared=False):
        state = self.state(device)
        return RoundInfo(device, g.acquisition, g.started, g.ended, state.exposure_s,
                         "cleared" if cleared else ("running" if state.running else g.reason or "paused"),
                         g.initial_settings, tuple(g.changes), state.duration_s, g.count_limit, float(g.window),
                         g.initial_outputs, tuple(g.output_changes), g.initial_duration,
                         g.initial_count_limit, tuple(g.target_changes), MappingProxyType(self.session.random_stream),
                         g.loaded_exposure, g.loaded_source, g.initial_window, tuple(g.window_changes))

    def configure(self, device, duration=_UNCHANGED, count_limit=_UNCHANGED, window=_UNCHANGED, *, _prepare=False):
        g = self._gate(device)
        if g.pending is not None:
            raise ValueError("Pause the instrument before changing acquisition targets")
        if duration is not _UNCHANGED and duration is not None:
            if type(duration) not in (int, float) or not isfinite(duration) or duration <= 0:
                raise ValueError("Acquisition duration must be finite and positive or None")
        if count_limit is not _UNCHANGED and count_limit is not None:
            if type(count_limit) is not int or count_limit <= 0:
                raise ValueError("Count limit must be a positive integer or None")
        if window is not _UNCHANGED:
            if type(window) not in (int, float) or not isfinite(window) or window <= 0:
                raise ValueError("Statistical window must be finite and positive")
        target = g.duration if duration is _UNCHANGED else (None if duration is None else Decimal(str(duration)))
        limit = g.count_limit if count_limit is _UNCHANGED else count_limit
        if g.opened is not None and (target != g.duration or limit != g.count_limit):
            raise ValueError("Pause the instrument before changing acquisition targets")
        if _prepare:
            return device, g, target, limit, window
        self._apply_configuration(device, g, target, limit, window)

    def _apply_configuration(self, device, g, target, limit, window):
        if window is not _UNCHANGED:
            requested = Decimal(str(window))
            previous = g.pending_window or g.window
            elapsed = self.state(device).exposure_s
            effective = g.next_check if Decimal(str(elapsed)) > g.window_start else g.readable_exposure
            if requested == g.window:
                g.pending_window = None
            elif Decimal(str(self.state(device).exposure_s)) > g.window_start:
                g.pending_window = requested
            else:
                g.window, g.pending_window = requested, None
                g.next_check = g.readable_exposure + g.window
            if requested != previous and g.current:
                g.window_changes.append(WindowChange(self.session.time_s, elapsed, float(requested), float(effective)))
        if target != g.duration or limit != g.count_limit:
            g.duration, g.count_limit = target, limit
            if g.current:
                self._note_targets(g)

    def _note_targets(self, g):
        g.target_changes.append(TargetChange(self.session.time_s, float(g.exposure),
                                             None if g.duration is None else float(g.duration), g.count_limit))

    def note_settings(self, values):
        values = self._configuration_change("settings", values)
        for device, g in self.gates.items():
            if g.current:
                g.changes.append(SettingChange(self.session.time_s, self.state(device).exposure_s,
                                               values))

    def _configuration_change(self, kind, values):
        immutable = MappingProxyType(dict(values))
        self.configuration_history.append(ConfigurationChange(len(self.configuration_history) + 1,
                                                               self.session.time_s, kind, immutable))
        return immutable

    def _activate_clock(self):
        if self.next_window is None:
            self.next_window = self.session._future_time(1)
            self.begin = self.session._time

    def _idle(self):
        if not self.clock_running:
            self.next_window = None

    def set_output(self, output, enabled):
        if output not in self.enabled:
            raise ValueError(f"Unknown detector output: {output}")
        if type(enabled) is not bool:
            raise ValueError("Detector output switch must be boolean")
        changes = {key: enabled for key in self._output_groups[output]
                   if enabled != self.enabled[key]}
        if not changes:
            return
        # Check clock resolution before committing the new switch position.
        if enabled and not self.clock_running:
            self.session._future_time(1)
        self.flush()
        self.enabled.update(changes)
        change = self._configuration_change("output", changes)
        for device, g in self.gates.items():
            if g.current:
                g.output_changes.append(SettingChange(self.session.time_s, self.state(device).exposure_s,
                                                      change))
        if enabled:
            self._activate_clock()
        self._idle()

    def _group(self, devices):
        if isinstance(devices, str):
            raise ValueError("Instrument group must contain distinct device ids")
        ids = tuple(devices)
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("Instrument group must contain distinct device ids")
        return [self._gate(device) for device in ids]

    def start_group(self, devices):
        self.start(None, None, _devices=self._group(devices))

    def configure_group(self, devices, duration, count_limit):
        ids = tuple(devices) if not isinstance(devices, str) else devices
        self._group(ids)
        prepared = [self.configure(device, duration, count_limit, _prepare=True) for device in ids]
        for values in prepared:
            self._apply_configuration(*values)

    def stop_group(self, devices):
        self.stop(None, _devices=self._group(devices))

    def start(self, device, duration, count_limit=None, window=None, *, _devices=None):
        gates = _devices if _devices is not None else (list(self.gates.values()) if device is None else [self._gate(device)])
        if any(g.pending is not None for g in gates):
            raise ValueError("Finish the instrument clear request before starting")
        if duration is not None:
            if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                    or not isfinite(duration) or duration <= 0):
                raise ValueError("Gate duration must be finite and positive")
            if any(g.opened is not None for g in gates):
                raise ValueError("Stop the current gate before starting a timed gate")
            self.session._future_time(duration)
        if count_limit is not None and (type(count_limit) is not int or count_limit <= 0):
            raise ValueError("Count limit must be a positive integer")
        if window is not None and (type(window) not in (int, float) or not isfinite(window) or window <= 0):
            raise ValueError("Statistical window must be finite and positive")
        if any(g.opened is not None for g in gates) and (count_limit is not None or window is not None):
            raise ValueError("Pause the instrument before changing acquisition limits")
        gates = [g for g in gates if g.opened is None]
        if not gates:
            return
        for g in gates:
            target = Decimal(str(duration)) if duration is not None else g.duration
            if g.current and ((target is not None and g.exposure >= target)
                              or (g.reason == "count_limit" and g.count_limit is not None
                                  and (count_limit if count_limit is not None else g.count_limit) <= sum(g.counts))):
                raise ValueError("Acquisition limit reached; change its target or clear before starting")
            if window is not None and g.current and Decimal(str(window)) != g.window:
                raise ValueError("Clear the instrument before changing its statistical window")
            check_after = (g.next_check - g.exposure if g.current else
                           Decimal(str(window)) if window is not None else g.window)
            self.session._future_time(float(check_after))
            if target is not None:
                self.session._future_time(float(target - g.exposure))
        self.session._future_time(1)
        self.flush()
        self._activate_clock()
        for g in gates:
            fresh = not g.current
            if not g.current:
                g.acquisition += 1
                g.current = True
                g.window = Decimal(str(window)) if window is not None else g.window
                g.next_check = g.window
                g.started = self.session.time_s
                g.initial_window = float(g.window)
                g.initial_settings = MappingProxyType(dict(self.session.settings))
                g.initial_outputs = MappingProxyType(dict(self.enabled))
            g.cycle += 1
            if duration is not None:
                g.duration = Decimal(str(duration))
            if count_limit is not None:
                g.count_limit = count_limit
            if fresh:
                g.initial_duration = None if g.duration is None else float(g.duration)
                g.initial_count_limit = g.count_limit
            elif duration is not None or count_limit is not None:
                self._note_targets(g)
            g.opened = self.session._time
            g.stop_at = None if g.duration is None else self.session._time + g.duration - g.exposure
            g.reason = None
            g.ended = None

    def stop(self, device, *, _devices=None):
        gates = _devices if _devices is not None else (list(self.gates.values()) if device is None else [self._gate(device)])
        if any(g.pending is not None for g in gates):
            raise ValueError("Finish the instrument clear request before stopping")
        if not any(g.opened is not None for g in gates):
            return
        self.flush()
        for g in gates:
            self._close(g, "manual")
        self._idle()

    def _close(self, g, reason):
        if g.opened is not None:
            g.exposure += self.session._time - g.opened
            g.opened = g.stop_at = None
            g.reason = reason
            g.ended = self.session.time_s

    def flush(self):
        if self.clock_running:
            self._sample(self.session._time)

    def advance(self, target):
        while self.clock_running:
            deadlines = [g.stop_at for g in self.gates.values() if g.stop_at is not None]
            deadlines.extend(self.session._time + g.next_check -
                             (g.exposure + self.session._time - g.opened)
                             for g in self.gates.values() if g.opened is not None)
            boundary = min([self.next_window, *deadlines])
            if boundary > target:
                self.session._time = target
                return
            self._sample(boundary)
            self.session._time = boundary
            for device, g in self.gates.items():
                full_window = g.opened is not None and g.readable_exposure >= g.next_check
                if full_window:
                    g.windows.append(self._window(device, g, True))
                    g.window_parts = []
                    g.window_counts = (0,) * len(g.counts)
                    g.window_start = g.readable_exposure
                    if g.pending_window is not None:
                        g.window, g.pending_window = g.pending_window, None
                    g.next_check += g.window
                if g.stop_at == boundary:
                    self._close(g, "time_limit")
                elif full_window and g.count_limit is not None and sum(g.counts) >= g.count_limit:
                    self._close(g, "count_limit")
            if boundary == self.next_window:
                self.next_window += 1
            self._idle()

    def _sample(self, boundary):
        if boundary == self.begin:
            return
        s = self.session
        start, end = float(self.begin), float(boundary)
        if not isfinite(end) or end <= start:
            raise ValueError("Exposure is below the physical clock resolution or outside its range")
        settings = MappingProxyType(s._settings.copy())
        rng_state = s._rng.getstate()
        try:
            definitions = s.experiment.outputs
            if any(self.enabled.values()):
                readings = s.experiment.model(settings, start, end, s._rng)
                if not isinstance(readings, Mapping):
                    raise ValueError("output must be a mapping of declared output ids")
                if readings.keys() != self.enabled.keys():
                    raise ValueError("output must match declared output ids")
                result = {}
                for output in definitions:
                    values = tuple(readings[output.id])
                    if len(values) != output.channels or any(type(v) is not int or v < 0 for v in values):
                        raise ValueError(f"{output.id}: expected {output.channels} nonnegative integer counts")
                    result[output.id] = values
            else:
                result = {}
            for output in definitions:
                if not self.enabled[output.id]:
                    result[output.id] = (0,) * output.channels
            rows = [Measurement(start, end, settings,
                                MappingProxyType({d.id: result[d.input]}),
                                self.gates[d.id].acquisition, signal=self._signals[d.id])
                    for d in s.experiment.devices if self.gates[d.id].opened is not None]
        except Exception as error:
            s._rng.setstate(rng_state)
            raise ValueError(f"{s.experiment.id}: sampling [{start}, {end}) failed: {error}") from error
        s.records.extend(rows)
        for row in rows:
            device, = row.readings
            g = self.gates[device]
            values = row.readings[device]
            g.counts = tuple(a + b for a, b in zip(g.counts, values))
            g.window_counts = tuple(a + b for a, b in zip(g.window_counts, values))
            g.window_parts.append(row)
            g.readable_exposure += boundary - self.begin
            if (g.segments and g.segments[-1].end_s == start
                    and g.segments[-1].origin == row.origin
                    and g.segments[-1].signal == row.signal
                    and g.segments[-1].settings == settings):
                old = g.segments[-1]
                merged = tuple(a + b for a, b in zip(old.readings[device], values))
                g.segments[-1] = Measurement(old.start_s, end, old.settings,
                                             MappingProxyType({device: merged}), g.acquisition, old.origin, old.signal)
            else:
                g.segments.append(row)
        self.begin = boundary

    def _window(self, device, g, complete):
        return InstrumentWindow(device, len(g.windows) + 1, g.acquisition,
                                float(g.window_start), float(g.readable_exposure),
                                g.window_counts, tuple(g.window_parts), complete, float(g.window))

    def instrument_windows(self, device):
        g = self._gate(device)
        return tuple(g.windows) + ((self._window(device, g, False),) if g.window_parts else ())

    def load_measurement(self, device, snapshot, *, overwrite=False):
        g = self._gate(device)
        if type(overwrite) is not bool:
            raise ValueError("Measurement overwrite confirmation must be boolean")
        if g.pending is not None:
            raise ValueError("Finish the instrument clear request before loading")
        if g.current and self.state(device).exposure_s > 0 and not overwrite:
            raise ValueError("Loading will overwrite current measurement data; confirmation required")
        if not isinstance(snapshot, Snapshot) or snapshot.device != device or not snapshot.segments:
            raise ValueError("Saved measurement belongs to another instrument or has no exposure")
        from .restoration import load_history
        source = replace(snapshot, id=max(1, snapshot.id))
        metadata = RoundInfo(device, source.acquisition, 0, None,
                             source.exposure_s, "loaded", source.segments[0].settings, (),
                             None, None, float(g.window), {}, (),
                             loaded_exposure_s=source.exposure_s, loaded_source=source.source or "load-validation")
        _, validated, _ = load_history(self.session.experiment, source.time_s, (metadata,), (source,), ())
        source = validated[0]
        # Validation precedes the only physical mutation: settle all current
        # gates, then replace this instrument while other gates remain open.
        self.flush()
        if g.current:
            self._close(g, "replaced")
            self._round_history.append(self._round_info(device, g))
        acquisition = g.acquisition + 1
        from uuid import uuid4
        origin = source.source or str(uuid4())
        rows = [replace(row, acquisition=acquisition, origin=row.origin or origin) for row in source.segments]
        windows = [replace(w, acquisition=acquisition,
                           parts=tuple(replace(p, acquisition=acquisition, origin=p.origin or origin) for p in w.parts)) for w in source.windows]
        loaded = _Gate(acquisition=acquisition, cycle=g.cycle, current=True,
                       exposure=Decimal(str(source.exposure_s)), readable_exposure=Decimal(str(source.exposure_s)),
                       duration=g.duration, count_limit=g.count_limit, window=g.window,
                       counts=source.counts, segments=rows, started=self.session.time_s,
                       loaded_exposure=source.exposure_s, loaded_source=origin,
                       initial_settings=MappingProxyType(dict(self.session.settings)), initial_outputs=MappingProxyType(dict(self.enabled)),
                       reason="loaded", ended=self.session.time_s,
                       initial_duration=None if g.duration is None else float(g.duration),
                       initial_count_limit=g.count_limit, window_counts=(0,) * len(source.counts))
        loaded.initial_window = float(g.window)
        loaded.window_prefix_exposure = source.window_prefix_exposure_s if source.windows else source.exposure_s
        loaded.window_prefix_counts = source.window_prefix_counts if source.windows else source.counts
        if windows and not windows[-1].complete:
            partial = windows.pop()
            loaded.window_parts = list(partial.parts)
            loaded.window_counts = partial.counts
            loaded.window_start = Decimal(str(partial.start_exposure_s))
            if partial.window_s is not None:
                loaded.window = Decimal(str(partial.window_s))
                loaded.next_check = loaded.window_start + loaded.window
                loaded.pending_window = g.window if g.window != loaded.window else None
            else:
                loaded.next_check = loaded.readable_exposure + g.window
        else:
            loaded.window_start = loaded.readable_exposure
            loaded.next_check = loaded.readable_exposure + g.window
        loaded.windows = windows
        self.gates[device] = loaded
        self._idle()

    def snapshot(self, device, *, cache=True, writer=None):
        g = self._gate(device)
        if not g.current or g.readable_exposure == 0:
            raise ValueError("There is no readable exposure for this instrument")
        item = Snapshot(self._snapshot_id + 1 if cache else 0, device, g.acquisition,
                        self.session.time_s, float(g.readable_exposure), g.counts, tuple(g.segments),
                        self.instrument_windows(device), None,
                        g.window_prefix_exposure, g.window_prefix_counts)
        if cache:
            if writer is not None:
                writer(item)
            self._snapshot_id += 1
            self.snapshots.append(item)
        return item

    def begin_clear(self, device):
        g = self._gate(device)
        if g.pending is not None:
            return g.pending.request
        was_running = g.opened is not None
        reason = g.reason
        if was_running:
            self.stop(device)
        self._clear_token += 1
        item = self.snapshot(device, cache=False) if g.readable_exposure else None
        request = ClearRequest(self._clear_token, device,
                               g.acquisition if g.current else None, item, was_running)
        g.pending = _Clear(request, reason)
        g.reason = "clearing"
        return request

    def finish_clear(self, device, token, choice, writer=None):
        g = self._gate(device)
        if type(token) is not int or g.pending is None or g.pending.request.token != token:
            raise ValueError("Instrument clear request has expired")
        if choice not in ("save", "discard", "cancel"):
            raise ValueError("Clear choice must be save, discard or cancel")
        pending = g.pending
        if choice == "cancel":
            self._restore(g, pending)
            return None
        saved = None
        try:
            if choice == "save" and pending.request.snapshot is not None:
                source = pending.request.snapshot
                saved = Snapshot(self._snapshot_id + 1, source.device, source.acquisition,
                                 source.time_s, source.exposure_s, source.counts, source.segments, source.windows, source.source,
                                 source.window_prefix_exposure_s, source.window_prefix_counts)
                if writer is not None:
                    writer(saved)
                self.snapshots.append(saved)
                self._snapshot_id += 1
        except Exception:
            self._restore(g, pending)
            raise
        # Old records and explicitly cached snapshots remain available. Only
        # this instrument's current round is discarded.
        if g.current:
            self._round_history.append(self._round_info(device, g, cleared=True))
        self.gates[device] = _Gate(acquisition=g.acquisition, cycle=g.cycle,
                                  duration=g.duration, count_limit=g.count_limit,
                                  window=g.pending_window or g.window, next_check=g.pending_window or g.window,
                                  counts=(0,) * len(g.counts), window_counts=(0,) * len(g.counts))
        self._idle()
        return saved

    def _restore(self, g, pending):
        # Finish input belonging only to the other active gates before this
        # gate reopens, including a partial physical window during confirmation.
        self.flush()
        g.pending = None
        g.reason = pending.reason
        if pending.request.was_running:
            self._activate_clock()
            # Resume the held round, preserving its unexpired exposure target.
            g.opened = self.session._time
            g.stop_at = None if g.duration is None else self.session._time + g.duration - g.exposure
            g.reason = None
            g.ended = None

    def clear(self, device=None):
        ids = tuple(self.gates) if device is None else (device,)
        for key in ids:
            request = self.begin_clear(key)
            self.finish_clear(key, request.token, "discard")
