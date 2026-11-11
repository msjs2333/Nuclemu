"""Measurement products and linear energy calibration for local instruments."""

import csv
from dataclasses import asdict, dataclass
import json
from math import isfinite, sqrt
from pathlib import Path


def net_count_rate(sample_counts, sample_exposure_s, background_counts, background_exposure_s):
    """Net rate and estimated standard uncertainty for independent Poisson counts."""
    for count, exposure in ((sample_counts, sample_exposure_s),
                            (background_counts, background_exposure_s)):
        if type(count) is not int or count < 0 or not isfinite(exposure) or exposure <= 0:
            raise ValueError("Counts must be nonnegative integers and exposure must be positive.")
    net = sample_counts / sample_exposure_s - background_counts / background_exposure_s
    variance = sample_counts / sample_exposure_s**2 + background_counts / background_exposure_s**2
    return net, sqrt(variance)


@dataclass(frozen=True)
class Calibration:
    experiment: str
    device: str
    channels: int
    channel1: float
    energy1: float
    channel2: float
    energy2: float

    def __post_init__(self):
        if not isinstance(self.device, str) or not self.device:
            raise ValueError("Calibration requires a device id.")
        values = (self.channel1, self.channel2, self.energy1, self.energy2)
        if not all(isfinite(v) for v in values):
            raise ValueError("Calibration points must be finite.")
        if not (0 <= self.channel1 < self.channel2 < self.channels and
                0 <= self.energy1 < self.energy2):
            raise ValueError("Use two increasing channels and energies within the instrument range.")

    def energy(self, channel):
        slope = (self.energy2 - self.energy1) / (self.channel2 - self.channel1)
        return self.energy1 + (channel - self.channel1) * slope

    def check(self, experiment, device, channels):
        if (self.experiment, self.device, self.channels) != (experiment, device, channels):
            raise ValueError("Calibration belongs to a different instrument configuration.")

    def save(self, path):
        Path(path).write_text(json.dumps({"format": "nuclemu.calibration/1", "unit": "MeV",
                                          **asdict(self)}, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or data.pop("format", None) != "nuclemu.calibration/1" or data.pop("unit", None) != "MeV":
            raise ValueError("Expected a Nuclemu energy calibration in MeV.")
        try:
            return cls(**data)
        except TypeError as exc:
            raise ValueError("Invalid calibration fields.") from exc


def roi_centroid(counts, first, last):
    """Count-weighted channel over an inclusive ROI; None for an empty peak."""
    if not 0 <= first <= last < len(counts):
        raise ValueError("ROI must lie within the spectrum and have increasing channel bounds.")
    total = weighted = 0
    for channel in range(first, last + 1):
        count = counts[channel]
        total += count
        weighted += channel * count
    return weighted / total if total else None


def _add_windows(segments, records):
    for row in records:
        if (not segments or row.acquisition != segments[-1]["acquisition"]
                or row.settings != segments[-1]["settings"] or row.start_s != segments[-1]["end_s"]):
            segments.append({"acquisition": row.acquisition, "start_s": row.start_s,
                             "end_s": row.end_s, "settings": dict(row.settings),
                             "readings": {key: list(values) for key, values in row.readings.items()}})
        else:
            segment = segments[-1]
            segment["end_s"] = row.end_s
            for key, values in row.readings.items():
                for i, value in enumerate(values):
                    segment["readings"][key][i] += value


def collect(experiment, records, seed):
    """Combine consecutive windows within one acquisition at unchanged settings."""
    segments = []
    _add_windows(segments, records)
    return {"format": "nuclemu.measurement/1", "experiment": experiment.id, "seed": seed,
            "devices": {d.id: {"kind": d.kind, "channels": d.channels} for d in experiment.devices},
            "segments": segments}


class MeasurementView:
    """A live product for one session. Callers treat its contents as read-only."""

    def __init__(self, session, seed=None):
        if seed is not None and seed != session.seed:
            raise ValueError("Measurement seed must match the session.")
        self._session = session
        self._next_record = 0
        self._product = collect(session.experiment, (), session.seed)

    def product(self):
        records = self._session.records
        if self._next_record < len(records):
            _add_windows(self._product["segments"], records[self._next_record:])
            self._next_record = len(records)
        return self._product


def save_product(path, product, device=None, calibration=None):
    path = Path(path)
    if not product["segments"]:
        raise ValueError("There is no completed exposure.")
    devices = product["devices"]
    if device is not None and device not in devices:
        raise ValueError(f"Unknown instrument: {device}")
    if calibration:
        key = calibration.device
        if key not in devices or (device is not None and device != key):
            raise ValueError("Calibration does not match the selected instrument.")
        calibration.check(product["experiment"], key, devices[key]["channels"])
    if path.suffix.lower() == ".json":
        selected = dict(product)
        if device:
            selected["devices"] = {device: devices[device]}
            selected["segments"] = [dict(s, readings={device: s["readings"][device]})
                                    for s in product["segments"]]
        if calibration:
            selected["calibration"] = dict(unit="MeV", **asdict(calibration))
        path.write_text(json.dumps(selected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return
    if path.suffix.lower() != ".csv":
        raise ValueError("Use .csv or .json for a measurement.")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("experiment", "device", "start_s", "end_s", "exposure_s", "settings",
                         "channel", "energy_MeV", "counts", "acquisition"))
        for s in product["segments"]:
            settings = json.dumps(s["settings"], sort_keys=True)
            exposure = s["end_s"] - s["start_s"]
            for key, values in s["readings"].items():
                if device is not None and key != device:
                    continue
                for channel, count in enumerate(values):
                    energy = calibration.energy(channel) if calibration and key == calibration.device else ""
                    writer.writerow((product["experiment"], key, s["start_s"], s["end_s"],
                                     exposure, settings, channel, energy, count, s.get("acquisition", "")))
