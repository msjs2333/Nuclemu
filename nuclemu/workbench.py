"""Shared operations for experiment setup, instrument readings and exports."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path

from .catalog import discover
from .core import Session
from .results import Calibration, MeasurementView, net_count_rate, roi_centroid, save_product


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

    def configure(self, values):
        # Validate the entire form before changing any physical condition.
        parameters = {p.key: p for p in self.session.experiment.parameters}
        checked = {key: parameters[key].value(float(value)) for key, value in values.items()}
        for key, value in checked.items():
            self.session.set(key, value)

    def set_speed(self, speed):
        speed = float(speed)
        if not isfinite(speed) or speed <= 0:
            raise ValueError("Simulation speed must be finite and positive.")
        self.speed = speed

    def start(self, duration=None):
        self.session.start(None if duration is None else float(duration))

    def stop(self):
        self.session.stop()

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
        return segments[-1 if index is None else index]

    def set_background(self, index):
        segments = self.product()["segments"]
        if index is not None and not 0 <= index < len(segments):
            raise ValueError("Select a completed background segment.")
        self.lab.background = index

    def spectrum_settings(self):
        segment = self.segment()
        return self.session.settings if segment is None else segment["settings"]

    def active_calibration(self):
        calibration = self.lab.calibrations.get(self.device.id)
        if calibration and calibration.applies_to(self.spectrum_settings()):
            return calibration
        return None

    def readout(self, first=0, last=None):
        segment = self.segment()
        if segment is None:
            return None
        counts = segment["readings"][self.device.id]
        exposure = segment["end_s"] - segment["start_s"]
        result = dict(counts=sum(counts), exposure_s=exposure, rate=sum(counts) / exposure)
        if self.device.kind == "spectrum":
            center = roi_centroid(counts, first, len(counts) - 1 if last is None else last)
            result["centroid"] = center
            calibration = self.active_calibration()
            result["energy_MeV"] = calibration.energy(center) if calibration and center is not None else None
        elif self.device.kind == "counter" and self.lab.background is not None:
            background = self.product()["segments"][self.lab.background]
            if background is segment:
                result["background_reference"] = True
            else:
                result["net_rate"], result["uncertainty"] = net_count_rate(
                    result["counts"], exposure, sum(background["readings"][self.device.id]),
                    background["end_s"] - background["start_s"],
                )
        return result

    def calibrate(self, channel1, energy1, channel2, energy2):
        if self.device.kind != "spectrum":
            raise ValueError("Energy calibration requires a spectrum instrument.")
        settings = self.spectrum_settings()
        conditions = tuple((key, settings[key]) for key in self.device.calibration_parameters)
        calibration = Calibration(self.current, self.device.id, self.device.channels,
                                  *map(float, (channel1, energy1, channel2, energy2)), conditions=conditions)
        self.lab.calibrations[self.device.id] = calibration
        return calibration

    def load_calibration(self, path):
        calibration = Calibration.load(path)
        self.apply_calibration(calibration)
        self._remember_file(path, {}, {(self.current, self.device.id): calibration})

    def apply_calibration(self, calibration):
        if self.device.kind != "spectrum":
            raise ValueError("Energy calibration requires a spectrum instrument.")
        calibration.check(self.current, self.device.id, self.device.channels,
                          self.device.calibration_parameters)
        if not calibration.applies_to(self.spectrum_settings()):
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
        indices = range(len(product["segments"])) if all_segments else (
            [len(product["segments"]) - 1 if self.lab.selected is None else self.lab.selected]
            if product["segments"] else []
        )
        indices = list(indices)
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
                   for d in self.session.experiment.devices)
