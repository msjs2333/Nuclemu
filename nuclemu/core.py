"""Public experiment definitions and the simulation-time acquisition loop."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from random import Random
from types import MappingProxyType


Number = int | float
Settings = Mapping[str, Number]
Readings = Mapping[str, Sequence[int]]
Model = Callable[[Settings, float, float, Random], Readings]
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

    def __post_init__(self):
        object.__setattr__(self, "parameters", tuple(self.parameters))


@dataclass(frozen=True)
class Connection:
    """A directed apparatus link; particle paths and signal cables are distinct."""

    source: str
    target: str
    kind: str
    label: str


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

    def __post_init__(self) -> None:
        if not self.id or not self.title or not callable(self.model):
            raise ValueError("Experiment requires an id, title and callable model")
        if not isinstance(self.course, str) or not self.course.strip():
            raise ValueError(f"{self.id}: course must be nonempty text")
        object.__setattr__(self, "parameters", tuple(self.parameters))
        object.__setattr__(self, "devices", tuple(self.devices))
        if isinstance(self.guide, str):
            raise ValueError(f"{self.id}: guide must be a sequence of paragraphs")
        object.__setattr__(self, "guide", tuple(self.guide))
        object.__setattr__(self, "components", tuple(self.components))
        object.__setattr__(self, "connections", tuple(self.connections))
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
        self._check_apparatus(parameter_keys)

    def _check_apparatus(self, parameter_keys: set[str]) -> None:
        if not isinstance(self.question, str) or any(not isinstance(p, str) or not p for p in self.guide):
            raise ValueError(f"{self.id}: question and guide paragraphs must be text")
        device_ids = {d.id for d in self.devices}
        component_ids = set()
        assigned_parameters = set()
        assigned_devices = set()
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
        if self.components and (parameter_keys != assigned_parameters or device_ids != assigned_devices):
            missing = sorted((parameter_keys - assigned_parameters) | (device_ids - assigned_devices))
            raise ValueError(f"{self.id}: missing apparatus binding for {', '.join(missing)}")
        for link in self.connections:
            if link.source not in component_ids or link.target not in component_ids:
                raise ValueError(f"{self.id}: unknown component in connection {link.source!r} to {link.target!r}")
            if link.kind not in {"particle", "signal"} or not link.label:
                raise ValueError(f"{self.id}: connection needs a particle or signal kind and a label")


@dataclass(frozen=True)
class Measurement:
    start_s: float
    end_s: float
    settings: Settings
    readings: Mapping[str, tuple[int, ...]]
    acquisition: int = 1

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
        self._time = Decimal(0)
        self._segment_start = self._time
        self._next_window: Decimal | None = None
        self._stop_at: Decimal | None = None
        self._device_ids = {d.id for d in experiment.devices}
        self.records: list[Measurement] = []
        self._acquisition = 0

    @property
    def seed(self) -> int:
        """The actual seed used to initialize this session's random stream."""
        return self._seed

    @property
    def time_s(self) -> float:
        return float(self._time)

    @property
    def running(self) -> bool:
        return self._next_window is not None

    @property
    def active_acquisition(self) -> int | None:
        """The existing acquisition number while its gate is open."""
        return self._acquisition if self.running else None

    @property
    def remaining_s(self) -> float | None:
        """Physical seconds left on a timed gate."""
        return None if self._stop_at is None else float(self._stop_at - self._time)

    def preview_stop(self) -> Measurement | None:
        """Read the unfinished interval for a save without committing a gate stop.

        Interval models derive their output from their arguments and use only
        the supplied random stream. A failed save can then resume the same run.
        """
        if not self.running or self._time == self._segment_start:
            return None
        preview_rng = Random(0)
        preview_rng.setstate(self._rng.getstate())
        return self._measure(self._time, preview_rng)

    @property
    def settings(self) -> Settings:
        return MappingProxyType(self._settings)

    def start(self, duration_s: Number | None = None) -> None:
        """Open the gate, optionally for a positive physical exposure.

        Calling start() on an open gate is harmless. A new timed gate requires
        stopping the existing gate first. Count-limited stopping is unavailable
        for interval models because they do not provide arrival times.
        """
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

    def stop(self) -> None:
        if self.running:
            self._sample_until(self._time)
            self._next_window = None
            self._stop_at = None

    def set(self, key: str, value: Number) -> None:
        if key not in self._parameters:
            raise ValueError(f"{self.experiment.id}: unknown parameter {key!r}")
        checked = self._parameters[key].value(value)
        if self._settings[key] != checked:
            if self.running:
                self._sample_until(self._time)
            self._settings[key] = checked

    def advance(self, seconds: Number) -> None:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError("Expected a duration in seconds")
        if not isfinite(seconds) or seconds < 0:
            raise ValueError("Duration must be finite and nonnegative")
        # Decimal arithmetic keeps ten advances of 0.1 s on the 1 s boundary.
        target = self._future_time(seconds)
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
