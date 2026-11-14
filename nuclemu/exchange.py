"""Portable SQLite experiments and explicit, independently named saved products.

The capture boundary reads round metadata and manually cached snapshots only.
Neither saving a package nor opening one samples a model or settles a gate.
"""

from contextlib import closing
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
import csv
from io import BytesIO, StringIO
from hashlib import sha256
import json
from math import isclose, isfinite
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile
from threading import Lock
from types import MappingProxyType
from typing import TYPE_CHECKING
from uuid import UUID, uuid4, uuid5
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from .catalog import describe, resolve_saved_experiment
from .core import SignalBinding
from .download_names import calibration_label, download_prefix, measurement_label
from .results import Calibration, configuration_document, round_document, snapshot_product

if TYPE_CHECKING:
    from .acquisition import Snapshot


FORMAT = "nuclemu.experiment/1"
ITEM_FORMAT = "nuclemu.item/1"
PACKAGE_FORMAT = "nuclemu.package/1"
_csv_field_limit_lock = Lock()


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _copy(value):
    return json.loads(_json(value))


def _measurement_item(item, definition, container):
    """Preserve known contracts; infer only native observations of this container."""
    if (item["kind"] != "measurement" or item["source"]["package"] != container
            or item["source"]["item"] != item["id"]):
        return item
    if not any(row.get("origin") is None and "signal" not in row for row in item["document"]["segments"]):
        return item
    bindings = {d["id"]: d.get("input") for d in definition["devices"]}
    outputs = {o["id"] for o in definition.get("outputs", ())}
    product = item["document"]
    device = product["snapshot"]["device"]
    signal_input = bindings.get(device)
    if signal_input not in outputs:
        return item
    signal = SignalBinding(signal_input, tuple(key for key, value in bindings.items() if value == signal_input))
    def annotate(row):
        if row.get("origin") is None and "signal" not in row:
            return dict(row, signal=signal.document())
        return row
    # Copy only metadata being augmented; immutable count arrays stay shared.
    return dict(item, document=dict(product, segments=[annotate(row) for row in product["segments"]],
        **({"windows": [dict(w, parts=[annotate(p) for p in w["parts"]]) for w in product["windows"]]}
           if "windows" in product else {})))


def capture_session(session, previous=None, *, definition=None, device=None, analysis=None, additional_snapshots=()):
    """Refresh metadata and include explicit snapshots; preserve prior item identities.

    Pass the previous document again after further sampling or reopening. Import
    and calibration items stay in that document. Analysis references are item
    UUIDs, never live product indices.
    """
    if not session.experiment.outputs:
        raise ValueError("Portable live capture requires explicit instrument snapshots")
    doc = dict(previous, items=list(previous["items"])) if previous is not None else dict(
        format=FORMAT, id=str(uuid4()), items=[], analysis={})
    if doc.get("format") != FORMAT:
        raise ValueError("Expected a portable Nuclemu experiment")
    if previous is not None and doc["definition"]["id"] != session.experiment.id:
        raise ValueError("Cannot capture a different experiment into this package")
    if previous is not None:
        doc["items"] = [_measurement_item(i, previous["definition"], doc["id"]) for i in doc["items"]]
    doc.update(definition=_copy(definition if definition is not None else describe(session.experiment)),
               seed=session.seed, random_stream=session.random_stream, configuration=configuration_document(session),
               rounds=[round_document(r) for r in session.rounds],
               device=device or doc.get("device", session.experiment.devices[0].id),
               instruments={})
    for d in session.experiment.devices:
        state = session.instrument(d.id)
        doc["instruments"][d.id] = {key: getattr(state, key) for key in (
            "running", "acquisition", "exposure_s", "remaining_s", "cycle", "count_limit",
            "duration_s", "window_s", "next_window_s", "stop_reason", "clearing")}
    if analysis is not None:
        doc["analysis"] = _copy(analysis)
    known = {item["id"] for item in doc["items"]}
    for snapshot in (*session.snapshots, *additional_snapshots):
        identity = native_snapshot_id(doc, snapshot)
        if identity not in known:
            doc["items"].append(dict(id=identity, kind="measurement",
                title=default_record_name(doc["definition"]),
                source=dict(package=doc["id"], item=identity),
                document=snapshot_product(session.experiment, snapshot, session.seed)))
            known.add(identity)
    validate_document(doc)
    return doc


def cache_calibration(doc, calibration, *, title=None):
    """Explicitly append one saved calibration; return its stable item UUID."""
    devices = {d["id"]: d for d in doc["definition"]["devices"]}
    d = devices.get(calibration.device)
    if d is None:
        raise ValueError("Calibration belongs to an unknown instrument")
    calibration.check(doc["definition"]["id"], d["id"], d["channels"], d.get("calibration_parameters", ()))
    identity = str(uuid4())
    item = dict(id=identity, kind="calibration", title=validate_record_name(title) if title is not None else default_record_name(doc["definition"]),
                source=dict(package=doc["id"], item=identity), document=calibration.document())
    doc["items"].append(item)
    return identity


def _item(doc, identity):
    found = next((i for i in doc["items"] if i["id"] == identity), None)
    if found is None:
        raise ValueError(f"Unknown saved item: {identity}")
    return found


def rename_record(doc, identity, title):
    """Rename by stable item identity; equal names never redirect references."""
    title = validate_record_name(title)
    for item in _record_items(doc, identity):
        item["title"] = title
    return identity


def default_record_name(definition):
    return download_prefix(definition)


def native_snapshot_id(doc, snapshot):
    return str(uuid5(UUID(doc["id"]), f"snapshot:{snapshot.id}"))


def link_measurements(doc, identities, title=None, *, members=None):
    """Mark one whole-instrument save on its first existing measurement item."""
    ids = list(identities)
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("Select distinct saved measurements")
    selected = [_item(doc, key) for key in ids]
    if any(i["kind"] != "measurement" for i in selected):
        raise ValueError("Only measurements can be saved together")
    scope = list(members) if members is not None else [i["document"]["snapshot"]["device"] for i in selected]
    name = validate_record_name(title if title is not None else default_record_name(doc["definition"]))
    primary = dict(selected[0], group=dict(items=ids, members=scope), title=name)
    replacements = {i["id"]: dict(i, title=name) for i in selected}
    replacements[ids[0]] = primary
    candidate = dict(doc, items=[replacements.get(i["id"], i) for i in doc["items"]])
    validate_document(candidate)
    doc["items"] = candidate["items"]
    return ids[0]


def validate_record_name(title):
    if not isinstance(title, str) or not title.strip():
        raise ValueError("A saved record name must not be empty")
    return title.strip()


def _record_items(doc, identity):
    item = _item(doc, identity)
    return [_item(doc, key) for key in item["group"]["items"]] if "group" in item else [item]


def bind_calibration(doc, measurement_id, calibration_id):
    measurement, calibration = _item(doc, measurement_id), _item(doc, calibration_id)
    if measurement["kind"] != "measurement" or calibration["kind"] != "calibration":
        raise ValueError("Bind a measurement item to a calibration item")
    _check_calibration(measurement, calibration)
    measurement["calibration_id"] = calibration_id


def _check_calibration(measurement, calibration):
    product = measurement["document"]
    cal = Calibration.from_document(calibration["document"])
    device = product["devices"].get(cal.device)
    if device is None:
        raise ValueError("Saved calibration belongs to another instrument")
    cal.check(product["experiment"], cal.device, device["channels"], device.get("calibration_parameters", ()))
    if any(not cal.applies_to(s["settings"]) for s in product["segments"]):
        raise ValueError("Saved calibration does not apply to the measurement settings")


def _number(value, label, *, positive=False):
    if type(value) not in (int, float) or not isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"Invalid {label}")


def _check_product(product):
    if not isinstance(product, dict) or product.get("format") != "nuclemu.measurement/1":
        raise ValueError("Expected a saved Nuclemu measurement")
    devices = product["devices"]
    if not devices or not product["segments"]:
        raise ValueError("A saved measurement requires actual exposure")
    if any(type(d["channels"]) is not int or d["channels"] < 1 for d in devices.values()):
        raise ValueError("Instrument channels must be positive integers")
    exposure, previous_end = 0, {}
    for segment in product["segments"]:
        if "signal" in segment:
            if not isinstance(segment["signal"], dict):
                raise ValueError("Invalid signal provenance")
            signal = SignalBinding(**segment["signal"])
            if not set(segment["readings"]) <= set(signal.consumers):
                raise ValueError("Signal provenance does not include the measured instrument")
        if segment.get("origin") is not None and (not isinstance(segment["origin"], str) or not segment["origin"]):
            raise ValueError("Invalid measurement origin")
        start, end = segment["start_s"], segment["end_s"]
        _number(start, "measurement start")
        _number(end, "measurement end")
        if end <= start or not segment["readings"]:
            raise ValueError("A saved measurement requires positive exposure")
        origin = segment.get("origin")
        if start < previous_end.get(origin, 0):
            raise ValueError("Measurement segments overlap within one source timeline")
        previous_end[origin] = end
        for key, counts in segment["readings"].items():
            if key not in devices or len(counts) != devices[key]["channels"]:
                raise ValueError("Measurement channels do not match the instrument")
            if any(type(c) is not int or c < 0 for c in counts):
                raise ValueError("Measurement counts must be nonnegative integers")
        exposure += end - start
    snapshot = product.get("snapshot")
    if snapshot is not None:
        device = snapshot["device"]
        if any(type(snapshot[key]) is not int or snapshot[key] < 1 for key in ("id", "acquisition")):
            raise ValueError("Invalid snapshot identity")
        if snapshot.get("source") is not None and (not isinstance(snapshot["source"], str) or not snapshot["source"]):
            raise ValueError("Invalid snapshot source identity")
        _number(snapshot["exposure_s"], "snapshot exposure", positive=True)
        _number(snapshot["time_s"], "snapshot time")
        if (set(devices) != {device}
                or any(set(s["readings"]) != {device} for s in product["segments"])
                or any(s["acquisition"] != snapshot["acquisition"] for s in product["segments"])
                or not isclose(exposure, snapshot["exposure_s"], rel_tol=1e-10, abs_tol=1e-10)
                or any(s["end_s"] > snapshot["time_s"] for s in product["segments"] if s.get("origin") is None)):
            raise ValueError("Snapshot cutoff exposure does not match its saved data")
    windows = product.get("windows", [])
    prefix = product.get("window_prefix", {"exposure_s": 0, "counts": []})
    _number(prefix["exposure_s"], "window prefix exposure")
    prefix_counts = prefix["counts"]
    if prefix["exposure_s"]:
        if (snapshot is None or len(prefix_counts) != devices[snapshot["device"]]["channels"]
                or any(type(c) is not int or c < 0 for c in prefix_counts)
                or prefix["exposure_s"] > snapshot["exposure_s"]):
            raise ValueError("Invalid unknown window prefix")
    if windows:
        if snapshot is None:
            raise ValueError("Instrument windows require a snapshot")
        end_exposure = prefix["exposure_s"]
        totals = list(prefix_counts) if end_exposure else [0] * devices[snapshot["device"]]["channels"]
        for number, window in enumerate(windows, 1):
            if (window["device"] != snapshot["device"] or window["number"] != number
                    or type(window["number"]) is not int or window["acquisition"] != snapshot["acquisition"]
                    or type(window["complete"]) is not bool
                    or not isclose(window["start_exposure_s"], end_exposure, abs_tol=1e-10)
                    or (not window["complete"] and number != len(windows))):
                raise ValueError("Invalid instrument window sequence")
            end_exposure = window["end_exposure_s"]
            part_product = dict(product, segments=window["parts"])
            part_product.pop("windows", None)
            part_product.pop("window_prefix", None)
            part_product["snapshot"] = dict(snapshot, exposure_s=end_exposure-window["start_exposure_s"])
            _check_product(part_product)
            counts = [sum(p["readings"][snapshot["device"]][i] for p in window["parts"])
                      for i in range(len(totals))]
            if counts != window["counts"]:
                raise ValueError("Window totals disagree with measured parts")
            totals = [a+b for a,b in zip(totals, counts)]
        expected = [sum(p["readings"][snapshot["device"]][i] for p in product["segments"])
                    for i in range(len(totals))]
        if totals != expected or not isclose(end_exposure, snapshot["exposure_s"], abs_tol=1e-10):
            raise ValueError("Instrument windows disagree with saved measurement")
        remaining, suffix = prefix["exposure_s"], []
        prefix_total = [0] * len(totals)
        for segment in product["segments"]:
            if remaining > 1e-10:
                remaining -= segment["end_s"]-segment["start_s"]
                prefix_total = [a+b for a,b in zip(prefix_total, segment["readings"][snapshot["device"]])]
            else:
                suffix.append(segment)
        if (abs(remaining) > 1e-10 or (prefix["exposure_s"] and prefix_total != prefix_counts)
                or _coalesce([p for w in windows for p in w["parts"]]) != _coalesce(suffix)):
            raise ValueError("Window conditions disagree with saved measurement")
    elif prefix["exposure_s"] and (not isclose(prefix["exposure_s"], snapshot["exposure_s"], abs_tol=1e-10)
            or prefix_counts != [sum(s["readings"][snapshot["device"]][i] for s in product["segments"])
                                 for i in range(len(prefix_counts))]):
        raise ValueError("Unknown window prefix disagrees with saved measurement")


def _coalesce(rows):
    """Compare the two saved views without merging different source timelines."""
    merged = []
    for row in rows:
        row = _copy(row)
        if row.get("origin") is None:
            row.pop("origin", None)
        previous = merged[-1] if merged else None
        if (previous is not None and previous["end_s"] == row["start_s"]
                and all(previous.get(k) == row.get(k) for k in ("settings", "acquisition", "origin", "signal"))
                and previous["readings"].keys() == row["readings"].keys()):
            previous["end_s"] = row["end_s"]
            for key, values in row["readings"].items():
                previous["readings"][key] = [a+b for a,b in zip(previous["readings"][key], values)]
        else:
            merged.append(row)
    return merged


def validate_document(doc):
    """Check the file boundary, preserving archived parameter values verbatim."""
    try:
        if doc.get("format") != FORMAT:
            raise ValueError("Unsupported Nuclemu experiment format")
        UUID(doc["id"])
        info = doc["definition"]
        devices = {d["id"]: d for d in info["devices"]}
        if not devices or doc["device"] not in devices:
            raise ValueError("The selected instrument is not defined")
        _number(doc["configuration"]["time_s"], "laboratory time")
        if not isinstance(doc["configuration"]["settings"], dict):
            raise ValueError("Saved settings must be a mapping")
        identifiers = set()
        for item in doc["items"]:
            UUID(item["id"])
            UUID(item["source"]["package"])
            UUID(item["source"]["item"])
            if item["id"] in identifiers or not isinstance(item["title"], str):
                raise ValueError("Duplicate saved item identity or invalid title")
            identifiers.add(item["id"])
            if item["kind"] == "measurement":
                _check_product(item["document"])
                if item["document"]["experiment"] != info["id"]:
                    raise ValueError("Saved measurement belongs to a different experiment")
                for key, d in item["document"]["devices"].items():
                    if key not in devices or any(devices[key][field] != d[field] for field in ("kind", "channels")):
                        raise ValueError("Saved measurement does not match the archived instrument")
            elif item["kind"] == "calibration":
                cal = Calibration.from_document(item["document"])
                d = devices.get(cal.device)
                if d is None or d["kind"] != "spectrum":
                    raise ValueError("Saved calibration belongs to an unknown spectrum instrument")
                cal.check(info["id"], cal.device, d["channels"], d.get("calibration_parameters", ()))
            else:
                raise ValueError("Unknown saved item kind")
        grouped = set()
        for item in doc["items"]:
            if "group" in item:
                group = item["group"]
                ids, members = group["items"], group["members"]
                if (item["kind"] != "measurement" or not isinstance(ids, list) or not ids
                        or ids[0] != item["id"] or len(set(ids)) != len(ids)
                        or not isinstance(members, list) or not members
                        or len(set(members)) != len(members) or not set(members) <= devices.keys()
                        or grouped.intersection(ids)):
                    raise ValueError("Invalid saved measurement group")
                actual = []
                for identity in ids:
                    member = _item(doc, identity)
                    if member["kind"] != "measurement" or (identity != item["id"] and "group" in member):
                        raise ValueError("Invalid saved measurement group member")
                    actual.append(member["document"]["snapshot"]["device"])
                if len(set(actual)) != len(actual) or not set(actual) <= set(members):
                    raise ValueError("Saved group does not match its instruments")
                grouped.update(ids)
        for item in doc["items"]:
            if item.get("calibration_id"):
                _check_calibration(item, _item(doc, item["calibration_id"]))
        for device, selection in doc.get("analysis", {}).items():
            if device not in devices:
                raise ValueError("Analysis belongs to an unknown instrument")
            for key in ("reference", "background", "selected"):
                identity = selection.get(key)
                if identity is not None:
                    item = _item(doc, identity)
                    if item["kind"] != "measurement" or device not in item["document"]["devices"]:
                        raise ValueError("Analysis must refer to a saved measurement from this instrument")
        for row in doc["rounds"]:
            if row["device"] not in devices or any(key in row for key in ("counts", "readings", "segments")):
                raise ValueError("Round metadata must not contain unsaved measurements")
            _number(row["exposure_s"], "round exposure")
        for state in doc.get("instruments", {}).values():
            if any(key in state for key in ("counts", "readings", "segments")):
                raise ValueError("Instrument metadata must not contain unsaved measurements")
        _json(doc)  # Reject nonfinite values and objects that SQLite cannot faithfully exchange.
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError("Incomplete or invalid portable experiment") from error
    return doc


def package_bytes(doc):
    """Build a .nuclemu ZIP containing a versioned manifest and SQLite database."""
    data = _sqlite_bytes(doc)
    manifest = dict(format=PACKAGE_FORMAT, version=1, schema=FORMAT,
                    id=doc["id"], experiment=doc["definition"]["id"],
                    database="experiment.sqlite3", sha256=sha256(data).hexdigest())
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", _json(manifest) + "\n")
        archive.writestr("experiment.sqlite3", data)
    return output.getvalue()


def _sqlite_bytes(doc):
    validate_document(doc)
    with closing(sqlite3.connect(":memory:")) as db, db:
        db.executescript("""
            PRAGMA user_version=1;
            CREATE TABLE manifest (data TEXT NOT NULL);
            CREATE TABLE rounds (idx INTEGER PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE items (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE segments (item TEXT NOT NULL, idx INTEGER NOT NULL, data TEXT NOT NULL,
                                   PRIMARY KEY(item, idx));
        """)
        db.execute("INSERT INTO manifest VALUES(?)", (_json({k: v for k, v in doc.items() if k not in ("items", "rounds")}),))
        db.executemany("INSERT INTO rounds VALUES(?,?)", ((i, _json(row)) for i, row in enumerate(doc["rounds"])))
        for item in doc["items"]:
            header = dict(item, document=dict(item["document"]))
            segments = header["document"].pop("segments", ())
            db.execute("INSERT INTO items VALUES(?,?)", (item["id"], _json(header)))
            db.executemany("INSERT INTO segments VALUES(?,?,?)",
                           ((item["id"], i, _json(row)) for i, row in enumerate(segments)))
        return db.serialize()


def save_package(path, doc):
    """Publish atomically; failed validation or writing leaves an existing file intact."""
    _save_bytes(path, package_bytes(doc))


def _save_bytes(path, data):
    destination = Path(path).resolve()
    stream = NamedTemporaryFile(dir=destination.parent, delete=False, suffix=".tmp")
    staged = Path(stream.name)
    try:
        with stream:
            stream.write(data)
        staged.replace(destination)
    finally:
        staged.unlink(missing_ok=True)


def load_package(source):
    """Open bytes or a path without a live experiment, catalogue, model or local store."""
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    manifest = None
    if not data.startswith(b"SQLite format 3\0"):
        try:
            with ZipFile(BytesIO(data)) as archive:
                if sorted(archive.namelist()) != ["experiment.sqlite3", "manifest.json"]:
                    raise ValueError("Experiment package must contain one manifest and one SQLite database")
                manifest = json.loads(archive.read("manifest.json"))
                if (manifest.get("format") != PACKAGE_FORMAT or manifest.get("version") != 1
                        or manifest.get("schema") != FORMAT or manifest.get("database") != "experiment.sqlite3"):
                    raise ValueError("Unsupported experiment package manifest")
                data = archive.read("experiment.sqlite3")
                if sha256(data).hexdigest() != manifest.get("sha256"):
                    raise ValueError("Experiment database does not match its manifest")
        except (BadZipFile, KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
            raise ValueError("Invalid .nuclemu experiment package") from error
    try:
        with closing(sqlite3.connect(":memory:")) as db:
            db.deserialize(data)
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("Unsupported experiment database version; convert legacy archives explicitly")
            sqlite_manifest, = db.execute("SELECT data FROM manifest").fetchall()
            doc = json.loads(sqlite_manifest[0])
            doc["rounds"] = [json.loads(row[0]) for row in db.execute("SELECT data FROM rounds ORDER BY idx")]
            doc["items"] = []
            for identity, header in db.execute("SELECT id,data FROM items ORDER BY rowid"):
                item = json.loads(header)
                if item["id"] != identity:
                    raise ValueError("Saved item identity does not match its database row")
                rows = list(db.execute("SELECT idx,data FROM segments WHERE item=? ORDER BY idx", (identity,)))
                if [row[0] for row in rows] != list(range(len(rows))):
                    raise ValueError("Saved measurement is missing data segments")
                if item["kind"] == "measurement":
                    item["document"]["segments"] = [json.loads(row[1]) for row in rows]
                doc["items"].append(item)
    except (sqlite3.Error, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError("Invalid portable SQLite experiment") from error
    validate_document(doc)
    if manifest and (manifest.get("id") != doc["id"] or manifest.get("experiment") != doc["definition"]["id"]):
        raise ValueError("Manifest identity does not match the experiment database")
    return doc


def _snapshot(product):
    from .acquisition import InstrumentWindow, Snapshot
    from .core import Measurement

    def parts(rows):
        return tuple(Measurement(s["start_s"], s["end_s"], MappingProxyType(dict(s["settings"])),
            MappingProxyType({key: tuple(counts) for key, counts in s["readings"].items()}), s["acquisition"], s.get("origin"),
            SignalBinding(**s["signal"]) if "signal" in s else None)
            for s in rows)
    metadata = product["snapshot"]
    device = metadata["device"]
    segments = parts(product["segments"])
    counts = tuple(sum(s.readings[device][i] for s in segments)
                   for i in range(product["devices"][device]["channels"]))
    windows = tuple(InstrumentWindow(w["device"], w["number"], w["acquisition"],
        w["start_exposure_s"], w["end_exposure_s"], tuple(w["counts"]), parts(w["parts"]), w["complete"], w.get("window_s"))
        for w in product.get("windows", ()))
    prefix = product.get("window_prefix", {"exposure_s": 0, "counts": []})
    return Snapshot(metadata["id"], device, metadata["acquisition"], metadata["time_s"],
                    metadata["exposure_s"], counts, segments, windows, metadata.get("source"),
                    prefix["exposure_s"], tuple(prefix["counts"]))


@dataclass(frozen=True)
class DecodedMeasurement:
    snapshot: "Snapshot"
    calibration: Calibration | None
    source: Mapping[str, str]
    item_id: str
    title: str


def _measurement_source(source):
    if not isinstance(source, dict):
        raw = source if isinstance(source, bytes) else Path(source).read_bytes()
        source = load_package(raw) if raw.startswith((b"PK", b"SQLite format 3")) else load_item(raw)
    if source.get("format") == FORMAT:
        validate_document(source)
        bundle = source
    elif source.get("format") == ITEM_FORMAT:
        bundle = load_item((_json(source)+"\n").encode("utf-8"))
    else:
        raise ValueError("Expected a portable experiment or saved item")
    return bundle


def decode_measurement(source, experiment, device, item_id=None):
    """Validate a saved measurement for loading, without changing a live session."""
    return _decode_measurement(_measurement_source(source), experiment, device, item_id)


def _decode_measurement(bundle, experiment, device, item_id):
    candidates = [i for i in bundle["items"] if i["kind"] == "measurement"]
    if item_id is None:
        if len(candidates) != 1:
            raise ValueError("Select one measurement item explicitly")
        item = candidates[0]
    else:
        item = next((i for i in candidates if i["id"] == item_id), None)
        if item is None:
            raise ValueError("Selected measurement is not in the source")
    restored = resolve_saved_experiment(experiment, bundle["definition"])
    bound = next((d for d in restored.devices if d.id == device), None)
    target = next((d for d in experiment.devices if d.id == device), None)
    product = _measurement_item(item, bundle["definition"], bundle.get("id", bundle.get("package")))["document"]
    saved = product["devices"].get(device)
    archived = next((d for d in bundle["definition"]["devices"] if d["id"] == device), None)
    if (product["experiment"] != experiment.id or bound is None or target is None or saved is None
            or product["snapshot"]["device"] != device or archived is None
            or (saved["kind"], saved["channels"]) != (target.kind, target.channels)
            or (saved["kind"], saved["channels"], archived.get("input")) !=
               (bound.kind, bound.channels, bound.input)):
        raise ValueError("Measurement does not match the target experiment and instrument")
    cal = (Calibration.from_document(_item(bundle, item["calibration_id"])["document"])
           if item.get("calibration_id") else None)
    snapshot = replace(_snapshot(product), source=f"{item['source']['package']}:{item['source']['item']}")
    return DecodedMeasurement(snapshot, cal, MappingProxyType(dict(item["source"])),
                              item["id"], item["title"])


def decode_measurements(source, experiment, devices, record_id=None):
    """Decode one saved instrument set; old single items stay single items."""
    source = _measurement_source(source)
    if record_id is None:
        choices = [i for i in list_records(source) if i["kind"] == "measurement"]
        if len(choices) != 1:
            raise ValueError("Select one saved measurement explicitly")
        record_id = choices[0]["id"]
    primary = _item(source, record_id)
    if primary["kind"] != "measurement":
        raise ValueError("Selected record is not a measurement")
    targets = tuple(devices)
    if not targets or len(set(targets)) != len(targets):
        raise ValueError("Select distinct target instruments")
    if "group" in primary and set(primary["group"]["members"]) != set(targets):
        raise ValueError("Saved instrument group does not match the target")
    result = []
    for item in _record_items(source, record_id):
        device = item["document"]["snapshot"]["device"]
        if device not in targets:
            raise ValueError("Saved measurement does not match the target instruments")
        result.append(_decode_measurement(source, experiment, device, item["id"]))
    return tuple(result)


def reopen_session(doc, experiment, *, seed=None):
    """Create a fresh idle live session with archived metadata and saved snapshots.

    A new derived random stream starts; unsaved readings are not restored. Legacy definitions remain
    readable, but must be imported as references into a new compatible course.
    """
    from .acquisition import ConfigurationChange, RoundInfo, SettingChange, TargetChange, WindowChange
    from .core import Session

    validate_document(doc)
    if doc.get("legacy") or experiment.id != doc["definition"]["id"]:
        raise ValueError("Open historical data for viewing, or import it into a new experiment")
    experiment = resolve_saved_experiment(experiment, doc["definition"])
    saved_outputs = {o["id"]: (o.get("channels", 1), o.get("unit", "count"),
                              o.get("time_unit", "s"), o.get("response", ""))
                     for o in doc["definition"].get("outputs", ())}
    current_outputs = {o.id: (o.channels, o.unit, o.time_unit, o.response) for o in experiment.outputs}
    if saved_outputs != current_outputs:
        raise ValueError("The current course does not match the archived signal output bindings")
    current_devices = {d.id: d for d in experiment.devices}
    for saved in doc["definition"]["devices"]:
        current = current_devices.get(saved["id"])
        if (current is None or (saved["kind"], saved["channels"], saved.get("input")) !=
                (current.kind, current.channels, current.input)):
            raise ValueError("The current course does not match the archived instrument binding")
    rounds = []
    for row in doc["rounds"]:
        values = dict(row)
        for key in ("changes", "output_changes"):
            values[key] = tuple(SettingChange(**v) for v in row.get(key, ()))
        values["target_changes"] = tuple(TargetChange(**v) for v in row.get("target_changes", ()))
        values["window_changes"] = tuple(WindowChange(**v) for v in row.get("window_changes", ()))
        rounds.append(RoundInfo(**values))
    snapshots = []
    for item in doc["items"]:
        if (item["kind"] != "measurement" or item["source"]["package"] != doc["id"]
                or item["source"]["item"] != item["id"]):
            continue
        product = _measurement_item(item, doc["definition"], doc["id"])["document"]
        snapshots.append(_snapshot(product))
    configuration = doc["configuration"]
    history = tuple(ConfigurationChange(**change) for change in configuration.get("history", ()))
    return Session.reopen(experiment, doc["seed"] if seed is None else seed,
                          settings=configuration["settings"], time_s=configuration["time_s"],
                          rounds=rounds, snapshots=snapshots, configuration_history=history,
                          random_stream=doc.get("random_stream"),
                          acquisition_settings={key: dict(duration_s=value["duration_s"],
                              count_limit=value["count_limit"],
                              window_s=value.get("next_window_s") if value.get("next_window_s") is not None else value["window_s"])
                              for key, value in doc.get("instruments", {}).items()})


def list_items(doc):
    return [dict(id=i["id"], kind=i["kind"], title=i["title"], source=i["source"],
                 device=i["document"].get("snapshot", {}).get("device", i["document"].get("device")),
                 exposure_s=i["document"].get("snapshot", {}).get("exposure_s")) for i in doc["items"]]


def list_records(doc):
    """Project saved items into student rows, keeping the first member's UUID."""
    by_id = {item["id"]: item for item in doc["items"]}
    companions = {key for i in doc["items"] for key in i.get("group", {}).get("items", [])[1:]}
    result = []
    for item, row in zip(doc["items"], list_items(doc)):
        if row["id"] in companions:
            continue
        if "group" in item:
            row["group"] = deepcopy(item["group"])
            row["measurements"] = [dict(id=i["id"], device=i["document"]["snapshot"]["device"],
                exposure_s=i["document"]["snapshot"]["exposure_s"])
                for i in (by_id[key] for key in item["group"]["items"])]
        result.append(row)
    return result


def _bundle(doc, identity):
    items = list(_record_items(doc, identity))
    for item in tuple(items):
        if item.get("calibration_id") and all(i["id"] != item["calibration_id"] for i in items):
            items.append(_item(doc, item["calibration_id"]))
    container = doc.get("id", doc.get("package"))
    return dict(format=ITEM_FORMAT, package=container, definition=doc["definition"],
                items=deepcopy([_measurement_item(i, doc["definition"], container) for i in items]),
                rounds=deepcopy(doc.get("rounds", [])))


def export_item(doc, identity, format="json"):
    """JSON includes the selected item and dependencies; CSV has one metadata line."""
    if doc.get("format") == ITEM_FORMAT:
        doc = load_item((_json(doc)+"\n").encode("utf-8"))
    else:
        validate_document(doc)
    bundle = _bundle(doc, identity)
    if format == "json":
        return (_json(bundle) + "\n").encode("utf-8")
    if format != "csv" or bundle["items"][0]["kind"] != "measurement":
        raise ValueError("Measurements support CSV/JSON; calibrations support JSON")
    return _export_csv(bundle)


_WINDOW_COLUMNS = ("experiment", "device", "window", "channel", "counts", "exposure_s", "parts")
_SEGMENT_COLUMNS = ("experiment", "device", "start_s", "end_s", "exposure_s", "settings",
                    "channel", "energy_MeV", "counts", "acquisition")


def _measurement_rows(product, calibration=None):
    if product.get("windows"):
        for window in product["windows"]:
            parts = _json(window["parts"])
            for channel, count in enumerate(window["counts"]):
                yield dict(experiment=product["experiment"], device=window["device"],
                    window=window["number"], channel=channel, counts=count,
                    exposure_s=window["end_exposure_s"]-window["start_exposure_s"],
                    parts=parts if channel == 0 else "")
    else:
        for segment in product["segments"]:
            settings = json.dumps(segment["settings"], sort_keys=True)
            apply_energy = calibration is not None and calibration.applies_to(segment["settings"])
            common = dict(experiment=product["experiment"], start_s=segment["start_s"],
                end_s=segment["end_s"], exposure_s=segment["end_s"]-segment["start_s"],
                settings=settings, acquisition=segment["acquisition"])
            if segment.get("origin") is not None:
                common["origin"] = segment["origin"]
            if segment.get("signal") is not None:
                common["signal"] = _json(segment["signal"])
            for device, counts in segment["readings"].items():
                for channel, count in enumerate(counts):
                    yield dict(common, device=device, channel=channel, counts=count,
                        energy_MeV=calibration.energy(channel) if apply_energy and device == calibration.device else "")


def _export_csv(bundle):
    measurements = [i for i in bundle["items"] if i["kind"] == "measurement"]
    grouped = len(measurements) > 1
    fields = ["item"] if grouped else []
    headers = []
    for item in bundle["items"]:
        product = item["document"]
        header = dict(item, document=dict(product))
        if item["kind"] == "measurement":
            columns = list(_WINDOW_COLUMNS if product.get("windows") else _SEGMENT_COLUMNS)
            if product.get("windows"):
                header["document"]["windows"] = [{k: v for k, v in w.items() if k not in ("counts", "parts")}
                                                   for w in product["windows"]]
            else:
                del header["document"]["segments"]
                columns.extend(key for key in ("origin", "signal") if any(p.get(key) is not None for p in product["segments"]))
            fields.extend(key for key in columns if key not in fields)
        headers.append(header)
    output = StringIO(newline="")
    output.write("# " + _json(dict(bundle, items=headers)) + "\n")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for item in measurements:
        calibration = Calibration.from_document(_item(bundle, item["calibration_id"])["document"]) if item.get("calibration_id") else None
        for row in _measurement_rows(item["document"], calibration):
            if grouped:
                row["item"] = item["id"]
            writer.writerow(row)
    return output.getvalue().encode("utf-8")


def load_item(source):
    """Load one exported item bundle, preserving source identity and calibration."""
    try:
        return _load_item(source)
    except (KeyError, TypeError, AttributeError, UnicodeError, csv.Error) as error:
        raise ValueError("Invalid saved item file") from error


class _MeasurementCSVReader:
    """Rebuild one instrument from its dispatched rows, then validate the bundle."""

    def __init__(self, product, windowed):
        self.product, self.windowed = product, windowed
        self.seen, self.groups, self.segments = set(), {}, []
        if windowed:
            for window in product["windows"]:
                window["counts"] = [None] * product["devices"][window["device"]]["channels"]

    def read(self, row):
        product = self.product
        if row["experiment"] != product["experiment"]:
            raise ValueError("CSV experiment disagrees with its saved metadata")
        device, channel = row["device"], int(row["channel"])
        if self.windowed:
            number = int(row["window"])
            if not 1 <= number <= len(product["windows"]):
                raise ValueError("CSV has an invalid window")
            window = product["windows"][number-1]
            if (device != window["device"] or not 0 <= channel < len(window["counts"])
                    or (number, channel) in self.seen
                    or not isclose(float(row["exposure_s"]),
                        window["end_exposure_s"]-window["start_exposure_s"], abs_tol=1e-10)):
                raise ValueError("CSV window disagrees with its metadata")
            self.seen.add((number, channel))
            window["counts"][channel] = int(row["counts"])
            if channel == 0:
                window["parts"] = json.loads(row["parts"])
            elif row["parts"]:
                raise ValueError("CSV window parts must occur once")
            return
        key = (device, float(row["start_s"]), float(row["end_s"]), row["settings"], int(row["acquisition"]),
               row.get("origin") or None, row.get("signal") or None)
        counts = self.groups.get(key)
        if counts is None:
            counts = [None] * product["devices"][device]["channels"]
            self.groups[key] = counts
            segment = dict(start_s=key[1], end_s=key[2], settings=json.loads(key[3]),
                           acquisition=key[4], readings={device: counts})
            if key[5] is not None:
                segment["origin"] = key[5]
            if key[6] is not None:
                segment["signal"] = json.loads(key[6])
            self.segments.append(segment)
        if not 0 <= channel < len(counts) or (key, channel) in self.seen:
            raise ValueError("CSV has duplicate or invalid instrument channels")
        if not isclose(float(row["exposure_s"]), key[2]-key[1], rel_tol=1e-10):
            raise ValueError("CSV exposure disagrees with its time bounds")
        self.seen.add((key, channel))
        counts[channel] = int(row["counts"])

    def finish(self):
        arrays = ([w["counts"] for w in self.product["windows"]] if self.windowed else self.groups.values())
        if not self.seen or any(any(c is None for c in counts) for counts in arrays):
            raise ValueError("CSV does not contain every instrument channel")
        if not self.windowed:
            self.product["segments"] = self.segments


def _load_item(source):
    raw = source if isinstance(source, bytes) else Path(source).read_bytes()
    text = raw.decode("utf-8-sig")
    if text.startswith("# "):
        metadata, body = text.split("\n", 1)
        bundle = json.loads(metadata[2:])
        # Read each CSV row once, dispatching by existing item UUID when grouped.
        with _csv_field_limit_lock:
            if len(body) > csv.field_size_limit():
                csv.field_size_limit(len(body))
        reader = csv.DictReader(StringIO(body))
        grouped = "item" in (reader.fieldnames or ())
        measurements = [i for i in bundle["items"] if i["kind"] == "measurement"]
        if not grouped and len(measurements) != 1:
            raise ValueError("CSV must identify each saved measurement")
        readers = {i["id"]: _MeasurementCSVReader(i["document"],
                   bool(i["document"].get("windows")) if grouped else "window" in (reader.fieldnames or ()))
                   for i in measurements}
        for row in reader:
            identity = row.get("item") if grouped else measurements[0]["id"]
            if identity not in readers:
                raise ValueError("CSV refers to an unknown measurement")
            readers[identity].read(row)
        for state in readers.values():
            state.finish()
    else:
        bundle = json.loads(text)
    if bundle.get("format") != ITEM_FORMAT or not bundle.get("items"):
        raise ValueError("Expected a portable Nuclemu saved item")
    # Validate through the same exchange boundary as a complete package.
    info = bundle["definition"]
    probe = dict(format=FORMAT, id=bundle["package"], definition=info, seed=0,
                 device=info["devices"][0]["id"], configuration=dict(time_s=0, settings={}),
                 instruments={}, analysis={}, rounds=bundle.get("rounds", []), items=bundle["items"])
    validate_document(probe)
    return bundle


def import_item(target, source, identity):
    """Append an independent copy with new UUIDs. Equal titles never replace data."""
    validate_document(target)
    bundle = _bundle(source, identity)
    if bundle.get("format") != ITEM_FORMAT:
        raise ValueError("Expected a package or saved item bundle")
    if bundle["definition"]["id"] != target["definition"]["id"]:
        raise ValueError("Reference belongs to a different experiment")
    chosen = next((i for i in bundle["items"] if i["id"] == identity), None)
    if chosen is None:
        raise ValueError("Selected item is not in the source file")
    copied = deepcopy(bundle["items"])
    remap = {item["id"]: str(uuid4()) for item in copied}
    devices = {d["id"]: d for d in target["definition"]["devices"]}
    for item in copied:
        if item["kind"] == "measurement":
            for key, device in item["document"]["devices"].items():
                if key not in devices or any(devices[key][field] != device[field] for field in ("kind", "channels")):
                    raise ValueError("Imported measurement belongs to a different instrument configuration")
        old = item["id"]
        item["id"] = remap[old]
        item.setdefault("source", dict(package=bundle["package"], item=old))
        if item.get("calibration_id"):
            item["calibration_id"] = remap[item["calibration_id"]]
        if "group" in item:
            item["group"]["items"] = [remap[key] for key in item["group"]["items"]]
    candidate = dict(target, items=[*target["items"], *copied])
    validate_document(candidate)
    target["items"].extend(copied)
    return remap[identity]


def batch_download(doc, selections):
    """Return (filename, MIME type, bytes), sharing one selection contract with Web."""
    if not selections:
        raise ValueError("Select saved items to download")
    prefix = download_prefix(doc["definition"])
    files = []
    for choice in selections:
        identity, format = choice["id"], choice["format"]
        item = _item(doc, identity)
        device = item["document"].get("snapshot", {}).get("device", item["document"].get("device", "instrument"))
        label = (calibration_label(doc["definition"], device) if item["kind"] == "calibration"
                 else measurement_label(doc["definition"], device))
        if len(item.get("group", {}).get("members", ())) > 1:
            kinds = {d["id"]: d["kind"] for d in doc["definition"]["devices"]}
            label = "counts" if all(kinds[d] == "counter" for d in item["group"]["members"]) else "measurements"
        files.append((f"{prefix}_{label}.{format}", export_item(doc, identity, format)))
    if len(files) == 1:
        name, data = files[0]
        return name, "text/csv; charset=utf-8" if name.endswith(".csv") else "application/json", data
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for index, (name, data) in enumerate(files, 1):
            archive.writestr(f"{prefix}_{index:03d}_{name[len(prefix)+1:]}", data)
    return f"{prefix}_records.zip", "application/zip", output.getvalue()


def package_download(doc):
    """Return the full experiment download, independent of checkbox selections."""
    return f"{download_prefix(doc['definition'])}.nuclemu", "application/zip", package_bytes(doc)


def save_item(path, doc, identity, format=None):
    _save_bytes(path, export_item(doc, identity, format or Path(path).suffix.lower().lstrip(".")))


def convert_archive(database, identifier):
    """Convert one independent legacy SQLite record without using live setters."""
    try:
        return _convert_archive(database, identifier)
    except (sqlite3.Error, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid legacy SQLite archive") from error


def list_legacy_archives(database):
    """List available archive ids without creating or modifying a local store."""
    try:
        with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA user_version").fetchone()[0] != 0:
                raise ValueError("Expected an existing legacy archive database")
            return [dict(id=i, kind=k, title=t, time_s=s, updated=u) for i, k, t, s, u in db.execute(
                "SELECT id,kind,title,time_s,updated FROM archives ORDER BY updated DESC,rowid DESC")]
    except sqlite3.Error as error:
        raise ValueError("Invalid legacy SQLite archive") from error


def _convert_archive(database, identifier):
    path = Path(database).resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        row = db.execute("SELECT metadata FROM archives WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("Legacy archive was not found")
        old = json.loads(row[0])
        rows = list(db.execute("SELECT idx,data FROM segments WHERE archive=? ORDER BY idx", (identifier,)))
        if [r[0] for r in rows] != list(range(len(rows))):
            raise ValueError("Legacy archive is missing measurement segments")
        old["product"]["segments"] = [json.loads(r[1]) for r in rows]
    info, product = old["definition"], old["product"]
    identity = str(uuid4())
    doc = dict(format=FORMAT, id=identity, definition=info, seed=product["seed"],
               device=old["device"], configuration=dict(initial_settings=deepcopy(old["settings"]),
               initial_outputs={}, history=[], settings=deepcopy(old["settings"]), output_enabled={},
               time_s=old["time_s"]), rounds=[], instruments={}, analysis={}, items=[],
               legacy=dict(archive=identifier, document=deepcopy(old)))
    calibrations = {}
    for key, fields in old.get("calibrations", {}).items():
        calibrations[key] = cache_calibration(doc, Calibration(**fields))
    references = {}
    for index, segment in enumerate(product["segments"]):
        for device, counts in segment["readings"].items():
            item_id = str(uuid4())
            acquisition = segment.get("acquisition", index + 1)
            selected = dict(product, devices={device: product["devices"][device]},
                segments=[dict(segment, readings={device: counts})],
                snapshot=dict(id=index + 1, device=device, acquisition=acquisition,
                              time_s=segment["end_s"], exposure_s=segment["end_s"] - segment["start_s"]))
            item = dict(id=item_id, kind="measurement", title=f"{device} · measurement {index + 1}",
                        source=dict(package=identity, item=item_id, archive=identifier), document=selected)
            if device in calibrations:
                cal = _item(doc, calibrations[device])
                if Calibration.from_document(cal["document"]).applies_to(segment["settings"]):
                    item["calibration_id"] = calibrations[device]
            doc["items"].append(_measurement_item(item, info, identity))
            references[index, device] = item_id
    for device, selection in old.get("analysis", {}).items():
        doc["analysis"][device] = deepcopy(selection)
        for key in ("selected", "reference", "background"):
            index = selection.get(key)
            doc["analysis"][device][key] = references.get((index, device)) if index is not None else None
    validate_document(doc)
    return doc
