"""Windows-safe download names based on the local wall-clock save time."""

from datetime import datetime, timedelta
import re
from threading import Lock

from .catalog import resolve_short_code


_lock = Lock()
_last_time = None


def safe_label(value):
    return re.sub(r"[^\w.-]+", "_", str(value)).strip(". ") or "record"


def measurement_label(definition, device):
    instrument = next((d for d in definition.get("devices", ()) if d["id"] == device), {})
    kind = {"spectrum": "spectrum", "counter": "counts"}.get(instrument.get("kind"), "measurement")
    if kind == "counts":
        group = next((p["devices"] for p in definition.get("components", ())
                      if device in p.get("devices", ()) and len(p["devices"]) > 1), None)
        if group:
            index = group.index(device)
            return f"counts-{chr(65+index) if index < 26 else index+1}"
    peers = [d for d in definition.get("devices", ()) if d.get("kind") == instrument.get("kind")]
    return kind if len(peers) == 1 else f"{kind}-{safe_label(device)}"


def calibration_label(definition, device):
    measurement = measurement_label(definition, device)
    return "calibration" + measurement[len("spectrum"):] if measurement.startswith("spectrum") else "calibration-" + safe_label(device)


def download_prefix(definition):
    """Allocate one stamp for an entire download, including every ZIP member."""
    global _last_time
    with _lock:
        now = datetime.now()
        # A coarse OS clock may return the same instant for adjacent requests.
        if _last_time is not None and now <= _last_time:
            now = _last_time + timedelta(microseconds=1)
        _last_time = now
    code = resolve_short_code(definition["id"], definition.get("short_code"))
    return f"{code}_{now:%Y%m%d-%H%M%S-%f}"
