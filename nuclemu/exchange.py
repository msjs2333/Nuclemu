"""Portable SQLite experiments and explicit, independently named saved products.

The capture boundary reads round metadata and manually cached snapshots only.
Neither saving a package nor opening one samples a model or settles a gate.
"""

from contextlib import closing
from copy import deepcopy
import csv
from io import BytesIO, StringIO
from hashlib import sha256
import json
from math import isclose, isfinite
from pathlib import Path
import re
import sqlite3
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4, uuid5
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from .catalog import describe
from .results import Calibration, configuration_document, round_document, snapshot_product, write_product


FORMAT = "nuclemu.experiment/1"
ITEM_FORMAT = "nuclemu.item/1"
PACKAGE_FORMAT = "nuclemu.package/1"


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _copy(value):
    return json.loads(_json(value))


def capture_session(session, previous=None, *, definition=None, device=None, analysis=None):
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
    doc.update(definition=_copy(definition if definition is not None else describe(session.experiment)),
               seed=session.seed, configuration=configuration_document(session),
               rounds=[round_document(r) for r in session.rounds],
               device=device or doc.get("device", session.experiment.devices[0].id),
               instruments={})
    for d in session.experiment.devices:
        state = session.instrument(d.id)
        doc["instruments"][d.id] = {key: getattr(state, key) for key in (
            "running", "acquisition", "exposure_s", "remaining_s", "cycle", "count_limit",
            "duration_s", "window_s", "stop_reason", "clearing")}
    if analysis is not None:
        doc["analysis"] = _copy(analysis)
    known = {item["id"] for item in doc["items"]}
    for snapshot in session.snapshots:
        identity = str(uuid5(UUID(doc["id"]), f"snapshot:{snapshot.id}"))
        if identity not in known:
            doc["items"].append(dict(id=identity, kind="measurement",
                title=f"{snapshot.device} · {snapshot.exposure_s:g} s",
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
    item = dict(id=identity, kind="calibration", title=title or f"{calibration.device} · calibration",
                source=dict(package=doc["id"], item=identity), document=calibration.document())
    doc["items"].append(item)
    return identity


def _item(doc, identity):
    found = next((i for i in doc["items"] if i["id"] == identity), None)
    if found is None:
        raise ValueError(f"Unknown saved item: {identity}")
    return found


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
    exposure = 0
    for segment in product["segments"]:
        start, end = segment["start_s"], segment["end_s"]
        _number(start, "measurement start")
        _number(end, "measurement end")
        if end <= start or not segment["readings"]:
            raise ValueError("A saved measurement requires positive exposure")
        for key, counts in segment["readings"].items():
            if key not in devices or len(counts) != devices[key]["channels"]:
                raise ValueError("Measurement channels do not match the instrument")
            if any(type(c) is not int or c < 0 for c in counts):
                raise ValueError("Measurement counts must be nonnegative integers")
        exposure += end - start
    snapshot = product.get("snapshot")
    if snapshot is not None:
        device = snapshot["device"]
        _number(snapshot["exposure_s"], "snapshot exposure", positive=True)
        _number(snapshot["time_s"], "snapshot time")
        if (set(devices) != {device}
                or any(set(s["readings"]) != {device} for s in product["segments"])
                or not isclose(exposure, snapshot["exposure_s"], rel_tol=1e-10, abs_tol=1e-10)
                or max(s["end_s"] for s in product["segments"]) > snapshot["time_s"]):
            raise ValueError("Snapshot cutoff exposure does not match its saved data")


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


def reopen_session(doc, experiment, *, seed=None):
    """Create a fresh idle live session with archived metadata and saved snapshots.

    No RNG state or unsaved readings are restored. Legacy definitions remain
    readable, but must be imported as references into a new compatible course.
    """
    from .acquisition import ConfigurationChange, RoundInfo, SettingChange, Snapshot, TargetChange
    from .core import Measurement, Session

    validate_document(doc)
    if doc.get("legacy") or experiment.id != doc["definition"]["id"]:
        raise ValueError("Open historical data for viewing, or import it into a new experiment")
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
        rounds.append(RoundInfo(**values))
    snapshots = []
    for item in doc["items"]:
        if (item["kind"] != "measurement" or item["source"]["package"] != doc["id"]
                or item["source"]["item"] != item["id"]):
            continue
        product = item["document"]
        metadata = product["snapshot"]
        segments = tuple(Measurement(s["start_s"], s["end_s"], s["settings"],
            {key: tuple(counts) for key, counts in s["readings"].items()}, s["acquisition"])
            for s in product["segments"])
        device = metadata["device"]
        counts = tuple(sum(s.readings[device][i] for s in segments)
                       for i in range(product["devices"][device]["channels"]))
        snapshots.append(Snapshot(metadata["id"], device, metadata["acquisition"],
                                  metadata["time_s"], metadata["exposure_s"], counts, segments))
    configuration = doc["configuration"]
    history = tuple(ConfigurationChange(**change) for change in configuration.get("history", ()))
    return Session.reopen(experiment, doc["seed"] if seed is None else seed,
                          settings=configuration["settings"], time_s=configuration["time_s"],
                          rounds=rounds, snapshots=snapshots, configuration_history=history,
                          acquisition_settings={key: {field: value[field] for field in
                              ("duration_s", "count_limit", "window_s")}
                              for key, value in doc.get("instruments", {}).items()})


def list_items(doc):
    return [dict(id=i["id"], kind=i["kind"], title=i["title"], source=i["source"],
                 device=i["document"].get("snapshot", {}).get("device", i["document"].get("device")),
                 exposure_s=i["document"].get("snapshot", {}).get("exposure_s")) for i in doc["items"]]


def _bundle(doc, identity):
    item = _item(doc, identity)
    items = [item]
    if item.get("calibration_id"):
        items.append(_item(doc, item["calibration_id"]))
    return dict(format=ITEM_FORMAT, package=doc["id"], definition=doc["definition"],
                items=deepcopy(items), rounds=deepcopy(doc["rounds"]))


def export_item(doc, identity, format="json"):
    """JSON includes the selected item and dependencies; CSV has one metadata line."""
    validate_document(doc)
    bundle = _bundle(doc, identity)
    if format == "json":
        return (_json(bundle) + "\n").encode("utf-8")
    if format != "csv" or bundle["items"][0]["kind"] != "measurement":
        raise ValueError("Measurements support CSV/JSON; calibrations support JSON")
    product = bundle["items"][0]["document"]
    header = deepcopy(bundle)
    del header["items"][0]["document"]["segments"]
    output = StringIO(newline="")
    output.write("# " + _json(header) + "\n")
    calibration = (Calibration.from_document(bundle["items"][1]["document"])
                   if len(bundle["items"]) == 2 else None)
    write_product(output, "csv", product, calibration=calibration)
    return output.getvalue().encode("utf-8")


def load_item(source):
    """Load one exported item bundle, preserving source identity and calibration."""
    try:
        return _load_item(source)
    except (KeyError, TypeError, AttributeError, UnicodeError, csv.Error) as error:
        raise ValueError("Invalid saved item file") from error


def _load_item(source):
    raw = source if isinstance(source, bytes) else Path(source).read_bytes()
    text = raw.decode("utf-8-sig")
    if text.startswith("# "):
        metadata, body = text.split("\n", 1)
        bundle = json.loads(metadata[2:])
        product = bundle["items"][0]["document"]
        segments, seen = [], set()
        groups = {}
        for row in csv.DictReader(StringIO(body)):
            if row["experiment"] != product["experiment"]:
                raise ValueError("CSV experiment disagrees with its saved metadata")
            device, channel = row["device"], int(row["channel"])
            key = (device, float(row["start_s"]), float(row["end_s"]), row["settings"], int(row["acquisition"]))
            counts = groups.get(key)
            if counts is None:
                counts = [None] * product["devices"][device]["channels"]
                groups[key] = counts
                segments.append(dict(start_s=key[1], end_s=key[2], settings=json.loads(key[3]),
                                     acquisition=key[4], readings={device: counts}))
            if not 0 <= channel < len(counts) or (key, channel) in seen:
                raise ValueError("CSV has duplicate or invalid instrument channels")
            if not isclose(float(row["exposure_s"]), key[2] - key[1], rel_tol=1e-10):
                raise ValueError("CSV exposure disagrees with its time bounds")
            seen.add((key, channel))
            counts[channel] = int(row["counts"])
        if any(any(c is None for c in values) for values in groups.values()):
            raise ValueError("CSV does not contain every instrument channel")
        product["segments"] = segments
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
    bundle = _bundle(source, identity) if source.get("format") == FORMAT else deepcopy(source)
    if bundle.get("format") != ITEM_FORMAT:
        raise ValueError("Expected a package or saved item bundle")
    if bundle["definition"]["id"] != target["definition"]["id"]:
        raise ValueError("Reference belongs to a different experiment")
    chosen = next((i for i in bundle["items"] if i["id"] == identity), None)
    if chosen is None:
        raise ValueError("Selected item is not in the source file")
    copied = [deepcopy(chosen)]
    if chosen.get("calibration_id"):
        calibration = next((i for i in bundle["items"] if i["id"] == chosen["calibration_id"]), None)
        if calibration is None:
            raise ValueError("Imported measurement is missing its associated calibration")
        copied.append(deepcopy(calibration))
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
    candidate = dict(target, items=[*target["items"], *copied])
    validate_document(candidate)
    target["items"].extend(copied)
    return remap[identity]


def batch_download(doc, selections):
    """Return (filename, MIME type, bytes), sharing one selection contract with Web."""
    if not selections:
        raise ValueError("Select saved items to download")
    files = []
    for choice in selections:
        identity, format = choice["id"], choice["format"]
        item = _item(doc, identity)
        stem = re.sub(r"[^\w.-]+", "_", item["title"]).strip(".") or "measurement"
        files.append((f"{stem}-{identity[:8]}.{format}", export_item(doc, identity, format)))
    if len(files) == 1:
        name, data = files[0]
        return name, "text/csv; charset=utf-8" if name.endswith(".csv") else "application/json", data
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for index, (name, data) in enumerate(files, 1):
            archive.writestr(f"{index}-{name}", data)
    return "nuclemu-saved-items.zip", "application/zip", output.getvalue()


def package_download(doc):
    """Return the full experiment download, independent of checkbox selections."""
    stem = re.sub(r"[^\w.-]+", "_", doc["definition"]["id"]).strip(".") or "experiment"
    return f"nuclemu-{stem}-experiment.nuclemu", "application/zip", package_bytes(doc)


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
            doc["items"].append(item)
            references[index, device] = item_id
    for device, selection in old.get("analysis", {}).items():
        doc["analysis"][device] = deepcopy(selection)
        for key in ("selected", "reference", "background"):
            index = selection.get(key)
            doc["analysis"][device][key] = references.get((index, device)) if index is not None else None
    validate_document(doc)
    return doc
