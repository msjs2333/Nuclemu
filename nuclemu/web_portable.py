"""Open portable saved measurements as an idle, continuable Web laboratory."""

from copy import deepcopy
import json

from .catalog import describe, resolve_saved_experiment
from .exchange import load_package
from .results import Calibration, MeasurementView
from .web_exchange import WebExchange


class SavedOverlay:
    """Immutable saved-item segments followed by this session's live view."""

    def __init__(self, session, items, *, live=None, package_id=None):
        self.session = session
        self.package_id = package_id
        self.live = MeasurementView(session) if live is None else live
        self.prefix = []
        self.item_indices = {}
        self._origins = []
        for item in items:
            if item["kind"] != "measurement":
                continue
            start = len(self.prefix)
            self.prefix.extend(deepcopy(item["document"]["segments"]))
            self._origins.extend([item['source']['package']] * len(item['document']['segments']))
            self.item_indices[item["id"]] = tuple(range(start, len(self.prefix)))
        self._product = None
        self._record_count = 0
        self.saved_end_s = max((s['end_s'] for s in self.prefix), default=0)

    def append_items(self, items):
        """Insert saved segments ahead of live history, retaining existing indices."""
        self.product()
        start = len(self.prefix)
        added = []
        for item in items:
            if item["kind"] != "measurement":
                continue
            if item["id"] in self.item_indices:
                raise ValueError("Saved item already appears in this view")
            first = start + len(added)
            segments = deepcopy(item["document"]["segments"])
            added.extend(segments)
            self._origins.extend([item['source']['package']] * len(segments))
            self.item_indices[item["id"]] = tuple(range(first, first + len(segments)))
        self.prefix.extend(added)
        self._product["segments"][start:start] = added
        self.saved_end_s = max(self.saved_end_s, max((s["end_s"] for s in added), default=0))
        return len(added)

    def product(self):
        live = self.live.product()
        # Preserve prefix segment identities for Workbench background comparisons.
        if self._product is None:
            self._product = dict(live, segments=list(self.prefix))
        count = len(self.session.records)
        if count != self._record_count:
            start = self.live.changed_start_since(self._record_count)
            self._product["segments"][len(self.prefix) + start:] = live["segments"][start:]
            self._record_count = count
        return self._product

    def changed_start_since(self, record_count):
        return len(self.prefix) + self.live.changed_start_since(record_count)

    def measurement_origin(self, index=None):
        return self._origins[index] if index is not None and index < len(self.prefix) else self.package_id


def _compatible(saved, current):
    """Require matching instrument and signal bindings before allowing continuation."""
    def signature(info):
        devices = {d["id"]: {key: d.get(key) for key in
                    ("kind", "channels", "input", "calibration_parameters")}
                   for d in info["devices"]}
        outputs = {o["id"]: {key: o.get(key) for key in ("channels", "response")}
                   for o in info.get("outputs", ())}
        return json.loads(json.dumps([devices, outputs], sort_keys=True))
    return signature(saved) == signature(current)


def open_portable(data, definitions, store, clock):
    """Decode a .nuclemu file and reopen its cached items without sampling."""
    from .web_session import WebLab  # Avoid a WebLab <-> adapter import cycle.

    doc = load_package(data)
    if "legacy" in doc:
        legacy = doc["legacy"]
        archive = legacy.get("document") if isinstance(legacy, dict) else None
        if not isinstance(archive, dict):
            raise ValueError("文件缺少只读查看所需的历史记录。")
        lab = WebLab.from_archive(archive, store, clock)
        course = definitions.get(lab.work.current)
        if not archive["definition"].get("short_code") and course and course.short_code:
            lab.info["short_code"] = course.short_code
        lab.portable_loaded = True
        return lab
    definition = definitions.get(doc["definition"]["id"])
    if definition is None:
        raise ValueError("找不到该可携文件对应的课程。")
    current = definition
    definition = resolve_saved_experiment(current, doc["definition"])
    info = describe(definition)
    if not _compatible(doc["definition"], info):
        raise ValueError("可携文件中的仪器或信号绑定与当前课程不符。")
    exchange, session = WebExchange.load(data, definition)
    lab = WebLab(definition, info, session.seed, store, clock)
    if definition is not current and ({d.id: d.input for d in definition.devices} !=
                                      {d.id: d.input for d in current.devices}):
        lab.portable_mode_notice = definition.description
    lab.work.lab.session = session
    overlay = SavedOverlay(session, doc["items"], package_id=doc['id'])
    lab.work.lab.view = overlay
    lab.exchange = exchange
    lab.portable_loaded = True
    lab.portable_unresolved = {}
    lab.portable_preserved_analysis = {}
    lab.portable_default_selection = {}

    # UUID references map to an index only when a whole item is one segment.
    for device, saved in doc.get("analysis", {}).items():
        target = lab.analysis[device]
        for key in ("roi", "energy_axis", "rate_axis"):
            if key in saved:
                target[key] = deepcopy(saved[key])
        unresolved = deepcopy(saved.get("unresolved", {}))
        for key in ("selected", "reference", "background"):
            identity = saved.get(key)
            if identity is None:
                continue
            if key in ('selected', 'reference'):
                lab.saved_measurement(identity, device)
                lab.saved_selection.setdefault(device, {})[key] = identity
                lab.saved_analysis.setdefault(device, {})[key] = identity
                unresolved.pop(key, None)
            indices = overlay.item_indices.get(identity, ())
            if len(indices) == 1:
                target[key] = indices[0]
            else:
                if key not in ('selected', 'reference'):
                    unresolved[key] = identity
                    lab.portable_preserved_analysis.setdefault(device, {})[key] = identity
        if unresolved:
            lab.portable_unresolved[device] = unresolved

    # Only explicitly saved calibration items are restored; a selected item's
    # binding takes precedence if several calibrations belong to one device.
    calibrations = {}
    for item in doc["items"]:
        if item["kind"] == "calibration":
            calibration = Calibration.from_document(item["document"])
            calibrations[item["id"]] = calibration
            lab.work.lab.calibrations[calibration.device] = calibration
    latest = next((item for item in reversed(doc["items"])
                   if item["kind"] == "measurement" and doc["device"] in item["document"]["devices"]), None)
    saved_selected = doc.get('analysis', {}).get(doc['device'], {}).get('selected')
    if latest and saved_selected is None:
        lab.saved_selection.setdefault(doc['device'], {})['selected'] = latest['id']
        indices = overlay.item_indices[latest["id"]]
        if len(indices) == 1:
            lab.analysis[doc["device"]]["selected"] = indices[0]
            if doc.get('analysis', {}).get(doc['device'], {}).get('selected') is None:
                lab.portable_default_selection[doc['device']] = indices[0]
        else:
            lab.analysis[doc["device"]]["selected"] = None
        calibration = calibrations.get(latest.get("calibration_id"))
        if calibration:
            lab.work.lab.calibrations[calibration.device] = calibration
    elif saved_selected is not None:
        selected_item = next((item for item in doc['items'] if item['id'] == saved_selected), None)
        calibration = calibrations.get(selected_item.get('calibration_id')) if selected_item else None
        if calibration:
            lab.work.lab.calibrations[calibration.device] = calibration
    lab.bind(doc["device"])
    lab.mark_saved()
    lab.draft_revision = lab.revision()
    lab.draft_segments = len(overlay.prefix)
    return lab
