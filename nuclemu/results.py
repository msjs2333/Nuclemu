"""Measurement products and linear energy calibration for local instruments."""

import csv
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
from math import isfinite, sqrt
from pathlib import Path
from tempfile import NamedTemporaryFile


@contextmanager
def _export_stream(path, *, newline=None):
    """Publish one complete file, following a destination symlink if present."""
    destination = Path(path).resolve()
    if destination.exists() and not destination.is_file():
        raise OSError(f"Expected a regular file: {destination}")
    stream = NamedTemporaryFile(mode="w", encoding="utf-8", newline=newline,
                                dir=destination.parent, suffix=".tmp", delete=False)
    staged = Path(stream.name)
    try:
        with stream:
            yield stream
        staged.replace(destination)
    finally:
        staged.unlink(missing_ok=True)


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
    conditions: tuple[tuple[str, float], ...] = ()

    def __post_init__(self):
        if not isinstance(self.device, str) or not self.device:
            raise ValueError("Calibration requires a device id.")
        pairs = tuple(sorted((key, value) for key, value in self.conditions))
        if (len(dict(pairs)) != len(pairs) or any(not isinstance(k, str)
                or type(v) not in (int, float) or not isfinite(v) for k, v in pairs)):
            raise ValueError("Invalid calibration conditions.")
        object.__setattr__(self, "conditions", pairs)
        values = (self.channel1, self.channel2, self.energy1, self.energy2)
        if not all(isfinite(v) for v in values):
            raise ValueError("Calibration points must be finite.")
        if not (0 <= self.channel1 < self.channel2 < self.channels and
                0 <= self.energy1 < self.energy2):
            raise ValueError("Use two increasing channels and energies within the instrument range.")

    def energy(self, channel):
        slope = (self.energy2 - self.energy1) / (self.channel2 - self.channel1)
        return self.energy1 + (channel - self.channel1) * slope

    def check(self, experiment, device, channels, parameters=()):
        if (self.experiment, self.device, self.channels) != (experiment, device, channels):
            raise ValueError("Calibration belongs to a different instrument configuration.")
        if set(dict(self.conditions)) != set(parameters):
            raise ValueError("Calibration must bind the instrument's calibration parameters.")

    def applies_to(self, settings):
        return all(settings.get(key) == value for key, value in self.conditions)

    def _fields(self):
        data = asdict(self)
        if self.conditions:
            data["conditions"] = dict(self.conditions)
        else:
            del data["conditions"]
        return data

    def document(self):
        version = 2 if self.conditions else 1
        return {"format": f"nuclemu.calibration/{version}", "unit": "MeV", **self._fields()}

    def save(self, path):
        with _export_stream(path) as stream:
            json.dump(self.document(), stream, indent=2)
            stream.write("\n")

    @classmethod
    def load(cls, path):
        return cls.from_document(json.loads(Path(path).read_text(encoding="utf-8-sig")))

    @classmethod
    def from_document(cls, document):
        data = dict(document) if isinstance(document, dict) else {}
        version = data.pop("format", None) if isinstance(data, dict) else None
        if version not in ("nuclemu.calibration/1", "nuclemu.calibration/2") or data.pop("unit", None) != "MeV":
            raise ValueError("Expected a Nuclemu energy calibration in MeV.")
        if version == "nuclemu.calibration/2":
            if not isinstance(data.get("conditions"), dict) or not data["conditions"]:
                raise ValueError("A conditional calibration requires its bound settings.")
            data["conditions"] = tuple(data["conditions"].items())
        elif "conditions" in data:
            raise ValueError("Use the conditional calibration format for bound settings.")
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
    devices = {}
    for device in experiment.devices:
        info = {"kind": device.kind, "channels": device.channels}
        if device.calibration_parameters:
            info["calibration_parameters"] = list(device.calibration_parameters)
        devices[device.id] = info
    return {"format": "nuclemu.measurement/1", "experiment": experiment.id, "seed": seed, "devices": devices,
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
    with _export_stream(path, newline="") as stream:
        write_product(stream, Path(path).suffix.lower().removeprefix("."), product, device, calibration)


def write_product(stream, format, product, device=None, calibration=None):
    """Write the same measurement product to a download or a local UTF-8 file."""
    if not product["segments"]:
        raise ValueError("There is no completed exposure.")
    devices = product["devices"]
    if device is not None and device not in devices:
        raise ValueError(f"Unknown instrument: {device}")
    if calibration:
        key = calibration.device
        if key not in devices or (device is not None and device != key):
            raise ValueError("Calibration does not match the selected instrument.")
        calibration.check(product["experiment"], key, devices[key]["channels"],
                          devices[key].get("calibration_parameters", ()))
    if format == "json":
        selected = dict(product)
        if device:
            selected["devices"] = {device: devices[device]}
            selected["segments"] = [dict(s, readings={device: s["readings"][device]})
                                    for s in product["segments"]]
        if calibration:
            field = "conditional_calibration" if calibration.conditions else "calibration"
            selected[field] = dict(unit="MeV", **calibration._fields())
        json.dump(selected, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        return
    if format != "csv":
        raise ValueError("Use .csv or .json for a measurement.")
    writer = csv.writer(stream)
    writer.writerow(("experiment", "device", "start_s", "end_s", "exposure_s", "settings",
                     "channel", "energy_MeV", "counts", "acquisition"))
    for s in product["segments"]:
        apply_energy = calibration is not None and calibration.applies_to(s["settings"])
        settings = json.dumps(s["settings"], sort_keys=True)
        exposure = s["end_s"] - s["start_s"]
        for key, values in s["readings"].items():
            if device is not None and key != device:
                continue
            for channel, count in enumerate(values):
                energy = calibration.energy(channel) if apply_energy and key == calibration.device else ""
                writer.writerow((product["experiment"], key, s["start_s"], s["end_s"],
                                 exposure, settings, channel, energy, count, s.get("acquisition", "")))
