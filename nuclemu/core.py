"""Public experiment definitions and the simulation-time acquisition loop."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from random import Random
import re
from types import MappingProxyType, NotImplementedType


Number = int | float
Settings = Mapping[str, Number]
Readings = Mapping[str, Sequence[int]]
Model = Callable[[Settings, float, float, Random], Readings]
_UNCHANGED = object()


def resolve_short_code(experiment_id: str, short_code: str | None = None) -> str:
    """Return declared naming metadata, or a safe code derived from an old id."""
    if short_code is not None:
        if not isinstance(short_code, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", short_code) is None:
            raise ValueError("short_code must contain 1–32 ASCII letters, digits, underscores or hyphens, starting with a letter or digit")
        return short_code
    if not isinstance(experiment_id, str) or not experiment_id:
        raise ValueError("An experiment id is required to derive short_code")
    code = re.sub(r"[^A-Za-z0-9_-]+", "-", experiment_id).strip("-_")
    if not code or len(code) > 32:
        from hashlib import sha256
        digest = sha256(experiment_id.encode("utf-8")).hexdigest()[:8]
        code = f"{code[:23] or 'EXP'}-{digest}"
    return code
# Models return interval counts, never rates or invented event arrival times.


@dataclass(frozen=True)
class Parameter:
    key: str
    label: str
    unit: str
    default: Number
    minimum: Number
    maximum: Number
    integer: bool = False
    options: tuple[tuple[Number, str], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "options", tuple(
            (option["value"], option["label"]) if isinstance(option, Mapping) else tuple(option)
            for option in self.options
        ))

    def value(self, number: Number) -> Number:
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise ValueError(f"{self.key}: expected a numeric value")
        if not isfinite(number) or not self.minimum <= number <= self.maximum:
            raise ValueError(
                f"{self.key}: expected {self.minimum} to {self.maximum} {self.unit}"
            )
        if self.integer:
            if int(number) != number:
                raise ValueError(f"{self.key}: expected an integer")
            number = int(number)
        else:
            number = float(number)
        if self.options and not any(number == value for value, _ in self.options):
            raise ValueError(f"{self.key}: expected one of the declared options")
        return number


@dataclass(frozen=True)
class Device:
    id: str
    kind: str
    label: str
    channels: int = 1
    calibration_parameters: tuple[str, ...] = ()
    background_conditions: tuple[tuple[str, Number], ...] = ()
    input: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "calibration_parameters", tuple(self.calibration_parameters))
        conditions = self.background_conditions
        if isinstance(conditions, Mapping):
            conditions = conditions.items()
        object.__setattr__(self, "background_conditions", tuple(tuple(pair) for pair in conditions))


@dataclass(frozen=True)
class Component:
    """A selectable piece of apparatus with its model controls or instrument."""

    id: str
    kind: str
    label: str
    description: str = ""
    parameters: tuple[str, ...] = ()
    device: str | None = None
    illustration: str | None = None
    output: str | None = None
    devices: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "parameters", tuple(self.parameters))
        object.__setattr__(self, "devices", tuple(self.devices))
        object.__setattr__(self, "outputs", tuple(self.outputs))


@dataclass(frozen=True)
class Connection:
    """A directed apparatus link; particle paths and signal cables are distinct."""

    source: str
    target: str
    kind: str
    label: str


@dataclass(frozen=True)
class SignalOutput:
    """Interval counts after the detector response, shared without further loss.

    The model returns one integer per channel over [start_s, end_s). No event
    arrival times or additional efficiency are implied by this interface.
    """

    id: str
    label: str
    channels: int = 1
    unit: str = "count"
    time_unit: str = "s"
    response: str = ""


@dataclass(frozen=True)
class Experiment:
    id: str
    title: str
    description: str
    parameters: tuple[Parameter, ...]
    devices: tuple[Device, ...]
    model: Model
    question: str = ""
    guide: tuple[str, ...] = ()
    components: tuple[Component, ...] = ()
    connections: tuple[Connection, ...] = ()
    course: str = "核物理实验"
    outputs: tuple[SignalOutput, ...] = ()
    normalize_settings: Callable[[Settings], Settings] | None = None
    particle_flow: Callable[[Settings], Mapping] | None = None
    short_code: str | None = None
    restore_definition: Callable[[Mapping], Experiment | NotImplementedType] | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.title or not callable(self.model):
            raise ValueError("Experiment requires an id, title and callable model")
        object.__setattr__(self, "short_code", resolve_short_code(self.id, self.short_code))
        if self.normalize_settings is not None and not callable(self.normalize_settings):
            raise ValueError(f"{self.id}: normalize_settings must be callable")
        if self.particle_flow is not None and not callable(self.particle_flow):
            raise ValueError(f"{self.id}: particle_flow must be callable")
        if self.restore_definition is not None and not callable(self.restore_definition):
            raise ValueError(f"{self.id}: restore_definition must be callable")
        if not isinstance(self.course, str) or not self.course.strip():
            raise ValueError(f"{self.id}: course must be nonempty text")
        object.__setattr__(self, "parameters", tuple(self.parameters))
        object.__setattr__(self, "devices", tuple(self.devices))
        if isinstance(self.guide, str):
            raise ValueError(f"{self.id}: guide must be a sequence of paragraphs")
        object.__setattr__(self, "guide", tuple(self.guide))
        object.__setattr__(self, "components", tuple(self.components))
        object.__setattr__(self, "connections", tuple(self.connections))
        object.__setattr__(self, "outputs", tuple(self.outputs))
        if len({p.key for p in self.parameters}) != len(self.parameters):
            raise ValueError(f"{self.id}: duplicate parameter key")
        for p in self.parameters:
            if not p.key or not p.label or not isfinite(p.minimum) or not isfinite(p.maximum):
                raise ValueError(f"{self.id}: invalid parameter {p.key!r}")
            option_values = set()
            for option in p.options:
                if len(option) != 2:
                    raise ValueError(f"{p.key}: options must contain value/label pairs")
                value, label = option
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not isfinite(value) or not p.minimum <= value <= p.maximum
                        or (p.integer and int(value) != value)
                        or not isinstance(label, str) or not label.strip()):
                    raise ValueError(f"{p.key}: invalid option value or label")
                if value in option_values:
                    raise ValueError(f"{p.key}: duplicate option value")
                option_values.add(value)
            p.value(p.default)
        if not self.devices or len({d.id for d in self.devices}) != len(self.devices):
            raise ValueError(f"{self.id}: at least one device with a distinct id is required")
        parameter_keys = {p.key for p in self.parameters}
        parameters = {p.key: p for p in self.parameters}
        for device in self.devices:
            if not device.id or not device.kind or not device.label:
                raise ValueError(f"{self.id}: each device needs an id, kind and label")
            if type(device.channels) is not int or device.channels < 1:
                raise ValueError(f"{device.id}: channels must be a positive integer")
            if device.kind == "counter" and device.channels != 1:
                raise ValueError(f"{device.id}: a counter has one channel")
            keys = set(device.calibration_parameters)
            if not keys <= parameter_keys or len(keys) != len(device.calibration_parameters):
                raise ValueError(f"{device.id}: calibration_parameters must name distinct declared parameters")
            if device.background_conditions and device.kind != "counter":
                raise ValueError(f"{device.id}: background_conditions requires a counter")
            seen = set()
            for pair in device.background_conditions:
                if len(pair) != 2 or pair[0] not in parameter_keys or pair[0] in seen:
                    raise ValueError(f"{device.id}: background_conditions must name distinct declared parameters")
                key, value = pair
                parameters[key].value(value)
                seen.add(key)
        outputs = {output.id: output for output in self.outputs}
        if len(outputs) != len(self.outputs):
            raise ValueError(f"{self.id}: duplicate output id")
        for output in self.outputs:
            if (not output.id or not output.label or type(output.channels) is not int
                    or output.channels < 1 or output.unit != "count" or output.time_unit != "s"):
                raise ValueError(f"{self.id}: outputs require channels of counts on a seconds time base")
        for device in self.devices:
            if self.outputs:
                if device.input not in outputs:
                    raise ValueError(f"{device.id}: input must name a declared output")
                if device.channels != outputs[device.input].channels:
                    raise ValueError(f"{device.id}: input channel count does not match instrument")
            elif device.input is not None:
                raise ValueError(f"{device.id}: input requires declared outputs")
        self._check_apparatus(parameter_keys)

    def _check_apparatus(self, parameter_keys: set[str]) -> None:
        if not isinstance(self.question, str) or any(not isinstance(p, str) or not p for p in self.guide):
            raise ValueError(f"{self.id}: question and guide paragraphs must be text")
        device_ids = {d.id for d in self.devices}
        component_ids = set()
        assigned_parameters = set()
        assigned_devices = set()
        output_ids = {output.id for output in self.outputs}
        grouped_outputs = set()
        for part in self.components:
            if not part.id or part.id in component_ids or not part.label or not part.kind:
                raise ValueError(f"{self.id}: invalid or duplicate component {part.id!r}")
            component_ids.add(part.id)
            for key in part.parameters:
                if key not in parameter_keys:
                    raise ValueError(f"{self.id}/{part.id}: unknown parameter {key!r}")
                assigned_parameters.add(key)
            if part.device is not None:
                if part.device not in device_ids:
                    raise ValueError(f"{self.id}/{part.id}: unknown device {part.device!r}")
                assigned_devices.add(part.device)
            if (len(set(part.devices)) != len(part.devices) or not set(part.devices) <= device_ids
                    or (part.devices and part.device is not None and part.device not in part.devices)):
                raise ValueError(f"{self.id}/{part.id}: devices must bind distinct declared instruments including device")
            assigned_devices.update(part.devices)
            if part.output is not None and part.output not in output_ids:
                raise ValueError(f"{self.id}/{part.id}: unknown output {part.output!r}")
            if part.outputs:
                group = set(part.outputs)
                if (len(group) != len(part.outputs) or not group <= output_ids
                        or part.output not in group or group & grouped_outputs):
                    raise ValueError(f"{self.id}/{part.id}: outputs must bind distinct declared outputs including output, without overlapping groups")
                grouped_outputs.update(group)
        if self.components and (parameter_keys != assigned_parameters or device_ids != assigned_devices):
            missing = sorted((parameter_keys - assigned_parameters) | (device_ids - assigned_devices))
            raise ValueError(f"{self.id}: missing apparatus binding for {', '.join(missing)}")
        for link in self.connections:
            if link.source not in component_ids or link.target not in component_ids:
                raise ValueError(f"{self.id}: unknown component in connection {link.source!r} to {link.target!r}")
            if link.kind not in {"particle", "signal"} or not link.label:
                raise ValueError(f"{self.id}: connection needs a particle or signal kind and a label")


@dataclass(frozen=True)
class SignalBinding:
    """The original input and its declared consumers for one observation."""

    input: str
    consumers: tuple[str, ...]

    def __post_init__(self):
        if (not isinstance(self.input, str) or not self.input
                or not isinstance(self.consumers, (list, tuple)) or not self.consumers
                or any(not isinstance(key, str) or not key for key in self.consumers)
                or len(set(self.consumers)) != len(self.consumers)):
            raise ValueError("Signal provenance requires an input and distinct named consumers")
        object.__setattr__(self, "consumers", tuple(sorted(self.consumers)))

    def document(self):
        return dict(input=self.input, consumers=list(self.consumers))


@dataclass(frozen=True)
class Measurement:
    start_s: float
    end_s: float
    settings: Settings
    readings: Mapping[str, tuple[int, ...]]
    acquisition: int = 1
    origin: str | None = None
    signal: SignalBinding | None = None

    @property
    def exposure_s(self) -> float:
        return self.end_s - self.start_s


class Session:
    """One laboratory clock; GUI readouts never drive physical sampling.

    The model samples a physical interval once, when its one-second acquisition
    window closes, a setting changes, or the gate stops. Unfinished intervals
    survive advance() calls. A host pauses world time by not calling advance().
    """

    def __init__(self, experiment: Experiment, seed: int = 0):
        if type(seed) is not int:
            raise ValueError("Session seed must be an integer")
        self.experiment = experiment
        self._seed = seed
        self._parameters = {p.key: p for p in experiment.parameters}
        self._settings = {p.key: p.value(p.default) for p in experiment.parameters}
        self._rng = Random(seed)
        self._random_stream = {"scheme": "python-random-sha256-v1", "seed": seed, "generation": 0}
        self._time = Decimal(0)
        self._segment_start = self._time
        self._next_window: Decimal | None = None
        self._stop_at: Decimal | None = None
        self._device_ids = {d.id for d in experiment.devices}
        self.records: list[Measurement] = []
        self._acquisition = 0
        self._particle_flow = None
        self._instruments = None
        if experiment.outputs:
            from .acquisition import InstrumentAcquisition
            self._instruments = InstrumentAcquisition(self)

    @property
    def seed(self) -> int:
        """The user-supplied root seed; random_stream identifies the generation."""
        return self._seed

    @property
    def random_stream(self):
        return dict(self._random_stream)

    @property
    def particle_flow(self):
        """Deterministic apparatus display data, cached until settings change."""
        if self.experiment.particle_flow is None:
            return None
        if self._particle_flow is None:
            import json
            self._particle_flow = json.loads(json.dumps(
                self.experiment.particle_flow(self.settings), allow_nan=False))
        return self._particle_flow

    @property
    def time_s(self) -> float:
        return float(self._time)

    @property
    def running(self) -> bool:
        if self._instruments is not None:
            return self._instruments.running
        return self._next_window is not None

    @property
    def clock_running(self) -> bool:
        """Whether an output or instrument currently needs laboratory time."""
        return self.running if self._instruments is None else self._instruments.clock_running

    @property
    def output_enabled(self) -> Mapping[str, bool]:
        return MappingProxyType({}) if self._instruments is None else self._instruments.output_enabled

    def set_output(self, output: str, enabled: bool) -> None:
        """Switch an output and its declared component group atomically."""
        if self._instruments is None:
            raise ValueError("This experiment has no independent detector outputs")
        self._instruments.set_output(output, enabled)

    def instrument(self, device: str):
        """Return an immutable snapshot of one independently gated instrument."""
        if self._instruments is None:
            raise ValueError("This experiment uses a shared acquisition gate")
        return self._instruments.state(device)

    def snapshot(self, device: str, *, cache: bool = True, writer=None):
        """Capture completed readable data without sampling or stopping a gate."""
        if self._instruments is None:
            raise ValueError("Snapshots require independent instruments")
        return self._instruments.snapshot(device, cache=cache, writer=writer)

    def snapshot_group(self, devices, *, cache=True, writer=None):
        """Save all readable members together; zero-exposure members stay empty."""
        if self._instruments is None:
            raise ValueError("Snapshots require independent instruments")
        return self._instruments.snapshot_group(devices, cache=cache, writer=writer)

    def cache_snapshots(self, devices, snapshots, *, writer=None):
        """Publish captured observations without reading or stopping live gates."""
        if self._instruments is None:
            raise ValueError("Snapshots require independent instruments")
        return self._instruments.cache_snapshots(devices, snapshots, writer=writer)

    def load_measurements(self, devices, snapshots, *, overwrite=False):
        """Replace an explicit whole instrument after all saved members validate."""
        if self._instruments is None:
            raise ValueError("Loading requires independent instruments")
        self._instruments.load_measurements(devices, snapshots, overwrite=overwrite)

    def begin_clear_group(self, devices):
        if self._instruments is None:
            raise ValueError("Clearing requires independent instruments")
        return self._instruments.begin_clear_group(devices)

    def finish_clear_group(self, devices, tokens, choice, *, writer=None):
        if self._instruments is None:
            raise ValueError("Clearing requires independent instruments")
        return self._instruments.finish_clear_group(devices, tokens, choice, writer=writer)

    def instrument_windows(self, device: str):
        if self._instruments is None:
            raise ValueError("Instrument windows require declared detector outputs")
        return self._instruments.instrument_windows(device)

    def load_measurement(self, device: str, snapshot, *, overwrite=False):
        """Replace only one idle/current instrument after validating saved data."""
        if self._instruments is None:
            raise ValueError("Loading a measurement requires independent instruments")
        self._instruments.load_measurement(device, snapshot, overwrite=overwrite)

    def start_group(self, devices):
        """Open/continue an explicit instrument group at this one lab instant.

        All targets and bindings are checked before any gate is changed.
        Detector outputs and instruments outside the group remain untouched.
        """
        if self._instruments is None:
            raise ValueError("Instrument groups require independent gates")
        self._instruments.start_group(devices)

    def stop_group(self, devices):
        if self._instruments is None:
            raise ValueError("Instrument groups require independent gates")
        self._instruments.stop_group(devices)

    def group_state(self, devices):
        """Return whether this explicit group can start or pause at this instant."""
        if self._instruments is None:
            raise ValueError("Instrument groups require independent gates")
        return self._instruments.group_state(devices)

    def configure_group(self, devices, *, duration_s=_UNCHANGED, count_limit=_UNCHANGED):
        """Apply shared targets atomically; per-window lengths stay independent."""
        if self._instruments is None:
            raise ValueError("Instrument groups require independent gates")
        self._instruments.configure_group(devices, duration_s, count_limit)

    @classmethod
    def reopen(cls, experiment, seed=0, *, settings, time_s=0, rounds=(), snapshots=(),
               configuration_history=(), acquisition_settings=None, random_stream=None):
        """Open validated historical metadata and snapshots as a fresh idle lab.

        This restores no RNG continuation or unsaved measurements. Historic
        settings stay with their records; current settings must use the
        experiment's canonical keys, without invoking a live-command adapter.
        """
        session = cls(experiment, seed)
        from hashlib import sha256
        stream = random_stream if random_stream is not None else {"scheme": "python-random-sha256-v1", "seed": seed, "generation": 0}
        if (not isinstance(stream, Mapping) or stream.get("scheme") != "python-random-sha256-v1"
                or type(stream.get("seed")) is not int or type(stream.get("generation")) is not int
                or stream["generation"] < 0):
            raise ValueError("Unsupported or invalid saved random stream")
        generation = stream["generation"] + 1
        session._random_stream = {"scheme": stream["scheme"], "seed": seed, "generation": generation}
        material = f"python-random-sha256-v1:{seed}:{generation}".encode("ascii")
        session._rng.seed(int.from_bytes(sha256(material).digest(), "big"))
        if session._instruments is None:
            raise ValueError("Reopening for new acquisition requires declared detector outputs")
        if not isinstance(settings, Mapping) or settings.keys() != session._parameters.keys():
            raise ValueError("Reopened settings must match the current experiment's canonical parameters")
        checked = {key: parameter.value(settings[key]) for key, parameter in session._parameters.items()}
        if type(time_s) not in (int, float) or not isfinite(time_s) or time_s < 0:
            raise ValueError("Reopened laboratory time must be finite and nonnegative")
        from .restoration import load_history
        loaded_rounds, loaded_snapshots, loaded_changes = load_history(
            experiment, time_s, rounds, snapshots, configuration_history)
        session._settings.update(checked)
        session._time = Decimal(str(time_s))
        engine = session._instruments
        engine.begin = session._time
        engine._round_history = loaded_rounds
        engine.snapshots = loaded_snapshots
        engine.configuration_history = loaded_changes
        engine._snapshot_id = max((item.id for item in loaded_snapshots), default=0)
        effective_outputs = {key: False for key in engine.enabled}
        effective_settings = {p.key: p.value(p.default) for p in experiment.parameters}
        for change in loaded_changes:
            if change.kind == "output":
                effective_outputs.update(change.values)
            else:
                effective_settings.update(change.values)
        closed = {key: False for key in engine.enabled if effective_outputs.get(key)}
        if closed:
            engine._configuration_change("output", closed)
        changed = {key: value for key, value in checked.items() if effective_settings.get(key) != value}
        if changed:
            engine._configuration_change("settings", changed)
        for info in loaded_rounds:
            gate = engine.gates[info.device]
            gate.acquisition = max(gate.acquisition, info.acquisition)
        for device, targets in (acquisition_settings or {}).items():
            if not isinstance(targets, Mapping) or not targets.keys() <= {"duration_s", "count_limit", "window_s"}:
                raise ValueError("Reopened acquisition settings must contain only duration, count limit and window")
            session.configure_acquisition(device, **targets)
        return session

    @property
    def snapshots(self):
        return () if self._instruments is None else tuple(self._instruments.snapshots)

    @property
    def rounds(self):
        """Round metadata; this does not create saved measurement snapshots."""
        return () if self._instruments is None else self._instruments.rounds

    @property
    def configuration_history(self):
        return () if self._instruments is None else tuple(self._instruments.configuration_history)

    def begin_clear(self, device: str):
        if self._instruments is None:
            raise ValueError("Instrument clear requires independent instruments")
        return self._instruments.begin_clear(device)

    def pending_clear(self, device: str):
        """Read the same immutable clear request after reconnecting a view."""
        if self._instruments is None:
            return None
        pending = self._instruments._gate(device).pending
        return None if pending is None else pending.request

    def finish_clear(self, device: str, token: int, choice: str, *, writer=None):
        if self._instruments is None:
            raise ValueError("Instrument clear requires independent instruments")
        return self._instruments.finish_clear(device, token, choice, writer)

    def clear(self, *, device: str | None = None):
        if self._instruments is None:
            raise ValueError("Instrument clear requires independent instruments")
        self._instruments.clear(device)

    def configure_acquisition(self, device: str, *, duration_s=_UNCHANGED,
                              count_limit=_UNCHANGED, window_s=_UNCHANGED):
        """Change a paused instrument's cumulative targets without opening it.

        Omitted limits stay unchanged. Explicit None returns that limit to
        ordinary acquisition; a later start resumes the same measured round.
        """
        if self._instruments is None:
            raise ValueError("Independent acquisition settings require declared detector outputs")
        self._instruments.configure(device, duration_s, count_limit, window_s)

    @property
    def active_acquisition(self) -> int | None:
        """The existing acquisition number while its gate is open."""
        if self._instruments is not None:
            return self._instruments.active_acquisition
        return self._acquisition if self.running else None

    @property
    def remaining_s(self) -> float | None:
        """Physical seconds left on a timed gate."""
        if self._instruments is not None:
            return self._instruments.remaining_s
        return None if self._stop_at is None else float(self._stop_at - self._time)

    def preview_stop(self) -> Measurement | None:
        """Read the unfinished interval for a save without committing a gate stop.

        Interval models derive their output from their arguments and use only
        the supplied random stream. A failed save can then resume the same run.
        """
        if self._instruments is not None:
            raise ValueError("Independent instruments require explicit stop before exporting a partial window")
        if not self.running or self._time == self._segment_start:
            return None
        preview_rng = Random(0)
        preview_rng.setstate(self._rng.getstate())
        return self._measure(self._time, preview_rng)

    @property
    def settings(self) -> Settings:
        return MappingProxyType(self._settings)

    def start(self, duration_s: Number | None = None, *, device: str | None = None,
              count_limit: int | None = None, window_s: Number | None = None) -> None:
        """Open the gate, optionally for a positive physical exposure.

        Calling start() on an open gate is harmless. A new timed gate requires
        stopping the existing gate first. Independent instruments retain their
        round across manual pauses and check count limits at complete windows.
        The legacy shared-gate path supports manual and timed acquisition.
        """
        if self._instruments is not None:
            self._instruments.start(device, duration_s, count_limit, window_s)
            return
        if device is not None or count_limit is not None or window_s is not None:
            raise ValueError("Independent gates require declared detector outputs")
        if duration_s is not None:
            if (isinstance(duration_s, bool) or not isinstance(duration_s, (int, float))
                    or not isfinite(duration_s) or duration_s <= 0):
                raise ValueError("Gate duration must be finite and positive")
            if self.running:
                raise ValueError("Stop the current gate before starting a timed gate")
        if not self.running:
            # Both model timestamps and saved exposures use binary64 seconds.
            # Reject an unresolvable gate before changing acquisition state.
            next_window = self._future_time(1)
            stop_at = self._future_time(duration_s) if duration_s is not None else None
            self._acquisition += 1
            self._segment_start = self._time
            self._next_window = next_window
            self._stop_at = stop_at

    def stop(self, *, device: str | None = None) -> None:
        if self._instruments is not None:
            self._instruments.stop(device)
            return
        if device is not None:
            raise ValueError("Independent gates require declared detector outputs")
        if self.running:
            self._sample_until(self._time)
            self._next_window = None
            self._stop_at = None

    def set(self, key: str, value: Number) -> None:
        self.configure({key: value})

    def configure(self, values: Settings) -> None:
        """Normalize and validate one setting batch before applying it atomically.

        A course may translate its own legacy setting names here. Archive
        readers restore recorded settings directly, not through this setter.
        """
        batch = MappingProxyType(dict(values))
        if self.experiment.normalize_settings is not None:
            batch = self.experiment.normalize_settings(batch)
        checked = {}
        for key, value in batch.items():
            if key not in self._parameters:
                raise ValueError(f"{self.experiment.id}: unknown parameter {key!r}")
            checked[key] = self._parameters[key].value(value)
        changed = {key: value for key, value in checked.items() if self._settings[key] != value}
        if changed:
            if self._instruments is not None:
                self._instruments.flush()
            elif self.running:
                self._sample_until(self._time)
            self._settings.update(checked)
            self._particle_flow = None
            if self._instruments is not None:
                self._instruments.note_settings(changed)

    def advance(self, seconds: Number) -> None:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError("Expected a duration in seconds")
        if not isfinite(seconds) or seconds < 0:
            raise ValueError("Duration must be finite and nonnegative")
        # Decimal arithmetic keeps ten advances of 0.1 s on the 1 s boundary.
        target = self._future_time(seconds)
        if self._instruments is not None:
            self._instruments.advance(target)
            return
        while self._next_window is not None:
            boundary = self._next_window
            if self._stop_at is not None:
                boundary = min(boundary, self._stop_at)
            if boundary > target:
                break
            self._sample_until(boundary)
            self._time = boundary
            if boundary == self._stop_at:
                self._next_window = None
                self._stop_at = None
            else:
                self._next_window += 1
        self._time = target

    def _future_time(self, seconds: Number) -> Decimal:
        target = self._time + Decimal(str(seconds))
        resolved = float(target)
        if not isfinite(resolved) or (seconds > 0 and resolved <= float(self._time)):
            raise ValueError("Duration is below the physical clock resolution or outside its range")
        return target

    def _sample_until(self, boundary: Decimal) -> None:
        if boundary == self._segment_start:
            return
        rng_state = self._rng.getstate()
        try:
            row = self._measure(boundary, self._rng)
        except Exception:
            self._rng.setstate(rng_state)
            raise
        self.records.append(row)
        self._segment_start = boundary

    def _measure(self, boundary: Decimal, rng: Random) -> Measurement:
        start, end = float(self._segment_start), float(boundary)
        if not isfinite(end) or end <= start:
            raise ValueError("Exposure is below the physical clock resolution or outside its range")
        settings = MappingProxyType(self._settings.copy())
        try:
            readings = self.experiment.model(settings, start, end, rng)
            devices = self.experiment.devices
            if not isinstance(readings, Mapping) or readings.keys() != self._device_ids:
                raise ValueError(f"{self.experiment.id}: output must match declared device ids")
            result = {}
            for device in devices:
                values = tuple(readings[device.id])
                if len(values) != device.channels or any(type(v) is not int or v < 0 for v in values):
                    raise ValueError(f"{device.id}: expected {device.channels} nonnegative integer counts")
                result[device.id] = values
        except Exception as error:
            raise ValueError(f"{self.experiment.id}: sampling [{start}, {end}) failed: {error}") from error
        return Measurement(start, end, settings, MappingProxyType(result), self._acquisition)
