"""Shared operations for experiment setup, instrument readings and exports."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from uuid import UUID

from .catalog import discover
from .core import Session, _UNCHANGED
from .results import Calibration, MeasurementView, net_count_rate, roi_centroid, save_product, snapshot_product


def _source_namespace(source):
    """A decoded package:item UUID retains its package's physical timeline.

    Arbitrary source labels are opaque; a colon alone does not identify a
    package/item pair. Explicit per-segment origins survive later containers.
    """
    if isinstance(source, str):
        parts = source.rsplit(':', 1)
        try:
            if len(parts) == 2:
                UUID(parts[1])
            return str(UUID(parts[0]))
        except ValueError:
            pass
    return source


@dataclass
class _SavedFile:
    path: Path
    measurements: dict
    calibrations: dict


@dataclass
class _Lab:
    session: Session
    view: MeasurementView
    device: str
    selected: int | None = None
    background: int | None = None
    source: str | None = None
    calibrations: dict = field(default_factory=dict)
    files: list = field(default_factory=list)

    @property
    def saved(self):
        saved = {}
        for file in self.files:
            for (experiment, index, device), end in file.measurements.items():
                if experiment == self.session.experiment.id:
                    saved[index, device] = max(end, saved.get((index, device), end))
        return saved

    @property
    def saved_calibrations(self):
        experiment = self.session.experiment.id
        return {device: calibration for device, calibration in self.calibrations.items()
                if any(file.calibrations.get((experiment, device)) == calibration
                       for file in self.files)}


class Workbench:
    """Operate the simulated devices without tying time to a display.

    Each experiment keeps its own readings. Only advance() moves laboratory
    time; querying, drawing, selecting and exporting never sample a model.
    """

    def __init__(self, paths=(), *, definitions=None, seed=0):
        self.definitions = discover(paths) if definitions is None else definitions
        if not self.definitions:
            raise ValueError("No experiments are available.")
        self.seed = seed
        self.labs = {}
        self.saved_files = []
        self.current = None
        self.paused = False
        self.speed = 1.0
        self.switch(next(iter(self.definitions)))

    @property
    def lab(self):
        return self.labs[self.current]

    @property
    def session(self):
        return self.lab.session

    @property
    def device(self):
        return next(d for d in self.session.experiment.devices if d.id == self.lab.device)

    def switch(self, experiment):
        if experiment not in self.definitions:
            raise ValueError(f"Unknown experiment: {experiment}")
        if self.current is not None:
            self.stop()
        if experiment not in self.labs:
            session = Session(self.definitions[experiment], self.seed)
            self.labs[experiment] = _Lab(
                session, MeasurementView(session), session.experiment.devices[0].id,
                files=self.saved_files,
            )
        self.current = experiment

    def bind_device(self, device):
        if device not in {d.id for d in self.session.experiment.devices}:
            raise ValueError(f"Unknown instrument: {device}")
        self.lab.device = device
        segments = self.product()["segments"]
        if self.lab.selected is not None and device not in segments[self.lab.selected]["readings"]:
            self.lab.selected = None
        if self.lab.background is not None and device not in segments[self.lab.background]["readings"]:
            self.lab.background = None

    def configure(self, values):
        # Validate the entire form before changing any physical condition.
        self.session.configure({key: float(value) for key, value in values.items()})

    def set_speed(self, speed):
        speed = float(speed)
        if not isfinite(speed) or speed <= 0:
            raise ValueError("Simulation speed must be finite and positive.")
        self.speed = speed

    def start(self, duration=None, *, device=None, count_limit=None, window_s=None):
        self.session.start(None if duration is None else float(duration), device=device,
                           count_limit=count_limit, window_s=window_s)

    def stop(self, *, device=None):
        self.session.stop(device=device)

    def set_output(self, output, enabled):
        self.session.set_output(output, enabled)

    def snapshot(self, *, device=None, cache=True, writer=None):
        return self.session.snapshot(self.lab.device if device is None else device,
                                     cache=cache, writer=writer)

    def begin_clear(self, *, device=None):
        return self.session.begin_clear(self.lab.device if device is None else device)

    def finish_clear(self, token, choice, *, device=None, writer=None):
        return self.session.finish_clear(self.lab.device if device is None else device,
                                         token, choice, writer=writer)

    def clear(self, *, device=None):
        self.session.clear(device=device)

    def configure_acquisition(self, *, device=None, **targets):
        self.session.configure_acquisition(self.lab.device if device is None else device, **targets)

    def advance(self, wall_seconds):
        if not self.paused:
            self.session.advance(wall_seconds * self.speed)

    def product(self):
        return self.lab.view.product()

    def select(self, index):
        if index is not None and not 0 <= index < len(self.product()["segments"]):
            raise ValueError("Select a completed measurement segment.")
        self.lab.selected = index

    def segment(self):
        segments = self.product()["segments"]
        if not segments:
            return None
        index = self.lab.selected
        if index is None:
            return next((s for s in reversed(segments) if self.device.id in s["readings"]), None)
        segment = segments[index]
        return segment if self.device.id in segment["readings"] else None

    def set_background(self, index):
        segments = self.product()["segments"]
        if index is not None and not 0 <= index < len(segments):
            raise ValueError("Select a completed background segment.")
        if index is not None and self.device.id not in segments[index]["readings"]:
            raise ValueError("Background segment belongs to another instrument.")
        self.lab.background = index

    def spectrum_settings(self):
        segment = self.segment()
        return self.session.settings if segment is None else segment["settings"]

    def active_calibration(self):
        calibration = self.lab.calibrations.get(self.device.id)
        if calibration and all(calibration.applies_to(settings) for settings in self._spectrum_conditions()):
            return calibration
        return None

    def _spectrum_conditions(self):
        if self.session.experiment.outputs and self.lab.selected is None:
            if self.session.instrument(self.device.id).readable_exposure_s > 0:
                return tuple(row.settings for row in self.snapshot(cache=False).segments)
            return (self.session.settings,)
        return (self.spectrum_settings(),)

    def readout(self, first=0, last=None):
        segment = self.segment()
        cumulative_acquisition = None
        if self.session.experiment.outputs and self.lab.selected is None:
            current = self.session.instrument(self.device.id)
            if current.readable_exposure_s == 0:
                return None
            counts, exposure = current.counts, current.readable_exposure_s
            cumulative_acquisition = current.acquisition
        else:
            if segment is None:
                return None
            counts = segment["readings"][self.device.id]
            exposure = segment["end_s"] - segment["start_s"]
        return self._readout(segment, counts, exposure, first, last, cumulative_acquisition,
                             measurement_index=self.lab.selected)

    def readout_for(self, index, first=0, last=None):
        """Analyze one nonoverlapping historical segment without changing selection."""
        segments = self.product()["segments"]
        if type(index) is not int or not 0 <= index < len(segments):
            raise ValueError("Select a completed measurement segment")
        segment = segments[index]
        if self.device.id not in segment["readings"]:
            raise ValueError("Measurement segment belongs to another instrument")
        return self._readout(segment, segment["readings"][self.device.id],
                             segment["end_s"] - segment["start_s"], first, last, measurement_index=index)

    def _measurement_origin(self, index):
        origin = getattr(self.lab.view, "measurement_origin", None)
        if origin is not None:
            return origin(index)
        return self.lab.source if self.lab.source is not None else self.session

    def bind_source(self, source):
        """Associate this lab's native timeline with its captured package ID."""
        if not isinstance(source, str) or not source:
            raise ValueError("Measurement source must be a nonempty identity")
        if self.lab.source is not None and self.lab.source != source:
            raise ValueError("The native measurement source is already bound")
        self.lab.source = source

    def readout_snapshot(self, snapshot, first=0, last=None, *, calibration=None):
        """Read a whole saved spectrum, retaining every contributing condition."""
        if snapshot.device != self.device.id or len(snapshot.counts) != self.device.channels:
            raise ValueError("Saved measurement belongs to another instrument")
        if calibration is not None:
            if self.device.kind != "spectrum":
                raise ValueError("Energy calibration requires a spectrum instrument")
            calibration.check(self.session.experiment.id, self.device.id, self.device.channels,
                              self.device.calibration_parameters)
        if self.device.kind != "spectrum":
            return dict(counts=sum(snapshot.counts), exposure_s=snapshot.exposure_s,
                        rate=sum(snapshot.counts) / snapshot.exposure_s)
        return self._readout({"settings": snapshot.segments[-1].settings}, snapshot.counts,
                             snapshot.exposure_s, first, last,
                             conditions=tuple(row.settings for row in snapshot.segments), calibration=calibration)

    def _readout(self, segment, counts, exposure, first, last, cumulative_acquisition=None,
                 *, measurement_index=None, conditions=None, calibration=_UNCHANGED):
        result = dict(counts=sum(counts), exposure_s=exposure, rate=sum(counts) / exposure)
        if self.device.kind == "spectrum":
            last = len(counts) - 1 if last is None else last
            center = roi_centroid(counts, first, last)
            result["roi_counts"] = sum(counts[first:last + 1])
            result["centroid"] = center
            if calibration is _UNCHANGED:
                calibration = self.lab.calibrations.get(self.device.id)
            if conditions is None:
                conditions = (segment["settings"],) if cumulative_acquisition is None else self._spectrum_conditions()
            if calibration and not all(calibration.applies_to(settings) for settings in conditions):
                calibration = None
            result["energy_MeV"] = calibration.energy(center) if calibration and center is not None else None
        elif self.device.kind == "counter" and self.lab.background is not None:
            background = self.product()["segments"][self.lab.background]
            if cumulative_acquisition is not None:
                source = self._measurement_origin(None)
                intervals = [(row.origin if row.origin is not None else source, row.start_s, row.end_s)
                             for row in self.snapshot(cache=False).segments]
            else:
                source = segment.get("origin")
                if source is None:
                    source = self._measurement_origin(measurement_index)
                intervals = [(source, segment["start_s"], segment["end_s"])]
            reference_source = background.get("origin")
            if reference_source is None:
                reference_source = self._measurement_origin(self.lab.background)
            background_interval = background["start_s"], background["end_s"]
            same_observation = (background is segment
                                and [(start, end) for _, start, end in intervals] == [background_interval]
                                and list(counts) == background["readings"][self.device.id]
                                and (cumulative_acquisition is None or all(
                                    source is not None and _source_namespace(source) == _source_namespace(reference_source)
                                    for source, _, _ in intervals)))
            if same_observation:
                result["background_reference"] = True
            else:
                if reference_source is None or any(source is None for source, _, _ in intervals):
                    raise ValueError("Measurement source is unknown; independent background subtraction is unavailable")
                # A plain in-memory view has no binding from its Session to
                # a package UUID. Different labels here do not prove independence.
                if any((source is self.session) != (reference_source is self.session)
                       for source, _, _ in intervals):
                    raise ValueError("Measurement source is unlinked; independent background subtraction is unavailable")
                reference_source = _source_namespace(reference_source)
                if any(_source_namespace(source) == reference_source
                       and max(start, background_interval[0]) < min(end, background_interval[1])
                       for source, start, end in intervals):
                    raise ValueError("Measurement includes the background exposure; select a nonoverlapping sample segment")
                result["net_rate"], result["uncertainty"] = net_count_rate(
                    result["counts"], exposure, sum(background["readings"][self.device.id]),
                    background["end_s"] - background["start_s"],
                )
        return result

    def calibrate(self, channel1, energy1, channel2, energy2):
        return self._calibrate((channel1, energy1, channel2, energy2), self._spectrum_conditions())

    def _snapshot_conditions(self, snapshot):
        if (snapshot.device != self.device.id or len(snapshot.counts) != self.device.channels
                or not snapshot.segments):
            raise ValueError("Saved measurement belongs to another instrument or has no spectrum")
        return tuple(row.settings for row in snapshot.segments)

    def calibrate_snapshot(self, snapshot, channel1, energy1, channel2, energy2):
        return self._calibrate((channel1, energy1, channel2, energy2), self._snapshot_conditions(snapshot))

    def _calibrate(self, points, settings_sequence):
        if self.device.kind != "spectrum":
            raise ValueError("Energy calibration requires a spectrum instrument.")
        settings = settings_sequence[0]
        if any(key not in settings for key in self.device.calibration_parameters):
            raise ValueError("Spectrum is missing its instrument calibration settings")
        conditions = tuple((key, settings[key]) for key in self.device.calibration_parameters)
        calibration = Calibration(self.session.experiment.id, self.device.id, self.device.channels,
                                  *map(float, points), conditions=conditions)
        if not all(calibration.applies_to(settings) for settings in settings_sequence):
            raise ValueError("Select a spectrum with matching instrument settings before calibrating")
        self.lab.calibrations[self.device.id] = calibration
        return calibration

    def load_calibration(self, path):
        calibration = Calibration.load(path)
        self.apply_calibration(calibration)
        self._remember_file(path, {}, {(self.current, self.device.id): calibration})

    def apply_calibration(self, calibration):
        self._apply_calibration(calibration, self._spectrum_conditions())

    def apply_snapshot_calibration(self, snapshot, calibration):
        self._apply_calibration(calibration, self._snapshot_conditions(snapshot))

    def _apply_calibration(self, calibration, settings_sequence):
        if self.device.kind != "spectrum":
            raise ValueError("Energy calibration requires a spectrum instrument.")
        calibration.check(self.session.experiment.id, self.device.id, self.device.channels,
                          self.device.calibration_parameters)
        if not all(calibration.applies_to(settings) for settings in settings_sequence):
            raise ValueError("Calibration does not match the selected spectrum's settings.")
        self.lab.calibrations[self.device.id] = calibration

    def save_calibration(self, path):
        calibration = self.active_calibration()
        if calibration is None:
            raise ValueError("请先为当前工况应用两点刻度。")
        calibration.save(path)
        self._remember_file(path, {}, {(self.current, self.device.id): calibration})

    def _remember_file(self, path, measurements, calibrations):
        # Record this application's explicit file operations, not external edits.
        # Atomic replacement changes one directory entry; other hard links keep their data.
        path = Path(path).resolve()
        self.saved_files[:] = [file for file in self.saved_files if file.path != path]
        self.saved_files.append(_SavedFile(path, measurements, calibrations))

    def export(self, path, *, all_segments=False):
        product = self.product()
        available = [i for i, s in enumerate(product["segments"]) if self.device.id in s["readings"]]
        if self.session.experiment.outputs and not all_segments and self.lab.selected is None:
            current = self.snapshot(cache=False)
            selected = snapshot_product(self.session.experiment, current, self.session.seed)
            indices = [i for i in available if product["segments"][i]["acquisition"] == current.acquisition]
        elif all_segments:
            indices = available
            selected = dict(product, segments=[product["segments"][i] for i in indices])
        elif self.lab.selected is None:
            indices = available[-1:]
            selected = dict(product, segments=[product["segments"][i] for i in indices])
        else:
            indices = [self.lab.selected] if self.lab.selected in available else []
            selected = dict(product, segments=[product["segments"][i] for i in indices])
        save_product(path, selected, self.device.id, self.lab.calibrations.get(self.device.id))
        calibrations = {}
        if Path(path).suffix.lower() == ".json" and self.device.id in self.lab.calibrations:
            calibrations[self.current, self.device.id] = self.lab.calibrations[self.device.id]
        self._remember_file(path, {
            (self.current, i, self.device.id): product["segments"][i]["end_s"] for i in indices
        }, calibrations)

    def unsaved(self):
        saved = self.lab.saved
        return any(saved.get((i, d.id)) != s["end_s"]
                   for i, s in enumerate(self.product()["segments"])
                   for d in self.session.experiment.devices if d.id in s["readings"])
