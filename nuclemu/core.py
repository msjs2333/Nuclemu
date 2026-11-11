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
            return int(number)
        return float(number)


@dataclass(frozen=True)
class Device:
    id: str
    kind: str
    label: str
    channels: int = 1
    calibration_parameters: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "calibration_parameters", tuple(self.calibration_parameters))


@dataclass(frozen=True)
class Experiment:
    id: str
    title: str
    description: str
    parameters: tuple[Parameter, ...]
    devices: tuple[Device, ...]
    model: Model

    def __post_init__(self) -> None:
        if not self.id or not self.title or not callable(self.model):
            raise ValueError("Experiment requires an id, title and callable model")
        object.__setattr__(self, "parameters", tuple(self.parameters))
        object.__setattr__(self, "devices", tuple(self.devices))
        if len({p.key for p in self.parameters}) != len(self.parameters):
            raise ValueError(f"{self.id}: duplicate parameter key")
        for p in self.parameters:
            if not p.key or not p.label or not isfinite(p.minimum) or not isfinite(p.maximum):
                raise ValueError(f"{self.id}: invalid parameter {p.key!r}")
            p.value(p.default)
        if not self.devices or len({d.id for d in self.devices}) != len(self.devices):
            raise ValueError(f"{self.id}: at least one device with a distinct id is required")
        parameter_keys = {p.key for p in self.parameters}
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
        start, end = float(self._segment_start), float(boundary)
        if not isfinite(end) or end <= start:
            raise ValueError("Exposure is below the physical clock resolution or outside its range")
        settings = MappingProxyType(self._settings.copy())
        rng_state = self._rng.getstate()
        try:
            readings = self.experiment.model(settings, start, end, self._rng)
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
            self._rng.setstate(rng_state)
            raise ValueError(f"{self.experiment.id}: sampling [{start}, {end}) failed: {error}") from error
        self.records.append(Measurement(start, end, settings, MappingProxyType(result), self._acquisition))
        self._segment_start = boundary
