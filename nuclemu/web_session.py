"""Server-owned clock, measurements, analysis selections and archive transactions."""

from copy import deepcopy
from base64 import b64decode
from dataclasses import asdict
from io import StringIO
import json
import sqlite3
from time import monotonic
from uuid import uuid4

from .catalog import describe
from .core import Device, Experiment, Parameter, SignalOutput
from .workbench import Workbench
from .results import Calibration, _add_windows, write_product
from .web_download import make_download
from .web_store import ArchiveStore
from .web_exchange import WebExchange
from .exchange import cache_calibration, bind_calibration, load_item, decode_measurement


def analysis_error(error):
    message = str(error)
    if 'includes the background exposure' in message:
        return '两份记录包含同一段曝光，请选择独立测量的本底。'
    if 'Measurement source is unknown' in message:
        return '记录来源不明确，暂不能按独立测量扣除本底。'
    return message


def window_state(row):
    """Serialize immutable settings without copying their mapping proxies."""
    return dict(device=row.device, number=row.number, acquisition=row.acquisition,
                start_exposure_s=row.start_exposure_s, end_exposure_s=row.end_exposure_s,
                counts=list(row.counts), complete=row.complete,
                parts=[dict(start_s=part.start_s, end_s=part.end_s,
                            settings=dict(part.settings), readings={k: list(v) for k, v in part.readings.items()})
                       for part in row.parts])


class ArchivedView:
    """A completed measurement product, opened without invoking an experiment model."""

    def __init__(self, product):
        self._product = product

    def product(self):
        return self._product


def archived_definition(info):
    def unavailable(*args):
        raise ValueError("历史记录仅供查看。")

    return Experiment(info["id"], info["title"], info["description"],
                      tuple(Parameter(**p) for p in info["parameters"]),
                      tuple(Device(**d) for d in info["devices"]), unavailable,
                      outputs=tuple(SignalOutput(**o) for o in info.get("outputs", ())))


class WebLab:
    def __init__(self, definition, info, seed, store, clock):
        self.info = info
        self.work = Workbench(definitions={definition.id: definition}, seed=seed)
        self.id = uuid4().hex
        self.archive_id = self.id
        self.draft_id = "draft-" + self.id
        self.store = store
        self.clock = clock
        self.last_tick = clock()
        self.frozen = False
        self.confirmation_id = None
        self._confirmation_serial = 0
        self.source = None
        self.archive_time = None
        self.archive_measurement_end = None
        self.archived_settings = None
        self.recovered_s = None
        self.analysis = {
            d.id: dict(roi=[0, d.channels - 1], reference=None, background=None,
                       selected=None, energy_axis=False, rate_axis=False)
            for d in definition.devices}
        self.edits = 0
        self.saved_revision = self.revision()
        self.draft_revision = self.saved_revision
        self.draft_segments = 0
        self.draft_error = None
        self._saved_ends = {}
        self._saved_settings = dict(self.settings())
        self._saved_analysis = deepcopy(self.analysis)
        self._saved_device = self.work.device.id
        self._saved_calibrations = {}
        self._pending = {}
        self._pending_entries = []
        self._dirty_records = -1
        self._dirty_segments = 0
        self.cache_writer = None
        self._clear_requests = {}
        self._snapshot_summaries = []
        self._counter_analysis_key = None
        self._counter_analysis = []
        self.exchange = WebExchange()
        self.portable_loaded = False
        self.product_generation = 0
        self._imported_count = 0
        self._imported_items = []
        self._live_calibrations = {}
        self._saved_calibration_devices = set()
        self.saved_selection = {}
        self.saved_analysis = {}
        self._decoded_items = {}

    def portable_download(self, selections=None):
        if self.readonly or not self.work.session.experiment.outputs:
            raise ValueError("此历史记录请使用旧库转存入口；当前可携文件用于显式保存的仪器读数。")
        analysis = deepcopy(self.analysis)
        for device, index in getattr(self, 'portable_default_selection', {}).items():
            if analysis[device]['selected'] == index:
                analysis[device]['selected'] = None
        self.exchange.refresh(self.work.session, device=self.work.device.id, definition=self.info,
                              product=self.work.product(), analysis=analysis,
                              item_indices=getattr(self.work.lab.view, 'item_indices', None),
                              preserved_analysis=getattr(self, 'portable_preserved_analysis', None), identity_analysis=self.saved_analysis)
        return self.exchange.download_package() if selections is None else self.exchange.download_selected(selections)

    def cache_calibration(self):
        calibration = self.selected_calibration()
        if calibration is None:
            raise ValueError("请先应用适用的能量刻度。")
        doc = self.exchange.refresh(self.work.session, device=self.work.device.id, definition=self.info,
                                    product=self.work.product(), analysis=self.analysis,
                                    item_indices=getattr(self.work.lab.view, 'item_indices', None),
                                    preserved_analysis=getattr(self, 'portable_preserved_analysis', None), identity_analysis=self.saved_analysis)
        identity = cache_calibration(doc, calibration)
        for item in doc['items']:
            if (item['kind'] == 'measurement' and not item.get('calibration_id') and calibration.device in item['document']['devices']
                    and all(calibration.applies_to(s['settings']) for s in item['document']['segments'])):
                bind_calibration(doc, item['id'], identity)
        self.exchange.document = doc
        self._decoded_items.clear()

    def bind_saved_calibration(self, snapshot):
        calibration = (self._live_calibrations.get(snapshot.device) if snapshot.device in self._saved_calibration_devices
                       else self.work.lab.calibrations.get(snapshot.device))
        doc = self.exchange.refresh(self.work.session, device=self.work.device.id, definition=self.info,
                                    product=self.work.product(), analysis=self.analysis,
                                    item_indices=getattr(self.work.lab.view, 'item_indices', None),
                                    preserved_analysis=getattr(self, 'portable_preserved_analysis', None), identity_analysis=self.saved_analysis)
        if calibration is None or not all(calibration.applies_to(row.settings) for row in snapshot.segments):
            return
        saved = next((item for item in reversed(doc['items']) if item['kind'] == 'calibration'
                      and item['document'] == calibration.document()), None)
        if saved:
            for item in doc['items']:
                if (item['kind'] == 'measurement' and item['document'].get('snapshot', {}).get('id') == snapshot.id
                        and item['document']['snapshot']['device'] == snapshot.device
                        and item['source']['package'] == doc['id'] and item['source']['item'] == item['id']):
                    bind_calibration(doc, item['id'], saved['id'])
            self.exchange.document = doc
            self._decoded_items.clear()

    def changed_start(self, old_count, old_length):
        """Use the shared view's cursor index for sparse, independently growing tails."""
        if old_count < 0:
            return 0
        if self.readonly:
            return old_length
        return self.work.lab.view.changed_start_since(old_count)

    @property
    def readonly(self):
        return self.archive_time is not None

    def revision(self):
        return self.edits, len(self.work.session.records)

    def sync(self):
        now = self.clock()
        elapsed = now - self.last_tick
        self.last_tick = now
        if not self.frozen and not self.readonly:
            self.work.advance(elapsed)

    def mark_saved(self, product=None):
        segments = (self.work.product() if product is None else product)["segments"]
        self._saved_ends = {(i, d): s["end_s"] for i, s in enumerate(segments)
                            for d in s["readings"]}
        self._saved_settings = dict(self.settings())
        self._saved_analysis = deepcopy(self.analysis)
        self._saved_device = self.work.device.id
        self._saved_calibrations = dict(self.work.lab.calibrations)
        self._pending.clear()
        self._pending_entries = []
        self._dirty_records = len(self.work.session.records)
        self._dirty_segments = len(segments)
        self.saved_revision = self.revision()

    def unsaved(self):
        w = self.work
        if w.session.experiment.outputs and not self.readonly:
            snapshots = w.session.snapshots
            measurements, active = [], []
            for d in w.session.experiment.devices:
                instrument = w.session.instrument(d.id)
                if instrument.running:
                    active.append(dict(device=d.id, remaining_s=instrument.remaining_s))
                if instrument.readable_exposure_s and not any(s.device == d.id and s.acquisition == instrument.acquisition
                        and s.exposure_s == instrument.readable_exposure_s for s in snapshots):
                    measurements.append(dict(index=instrument.acquisition - 1, acquisition=instrument.acquisition,
                                             device=d.id, end_s=instrument.readable_exposure_s))
            saved_calibrations = [i['document'] for i in (self.exchange.document or {}).get('items', ()) if i['kind'] == 'calibration']
            return dict(measurements=measurements,
                        calibrations=[key for key, cal in w.lab.calibrations.items() if cal.document() not in saved_calibrations],
                        analysis=self.analysis != self._saved_analysis or w.device.id != self._saved_device,
                        settings=self.settings() != self._saved_settings,
                        active_exposure=dict(devices=active) if active else None,
                        cached_items=len(snapshots) + len(saved_calibrations))
        count = len(w.session.records)
        if count != self._dirty_records:
            segments = w.product()["segments"]
            for i in range(self.changed_start(self._dirty_records, self._dirty_segments), len(segments)):
                segment = segments[i]
                for device in segment["readings"]:
                    key = i, device
                    if self._saved_ends.get(key) != segment["end_s"]:
                        self._pending[key] = dict(index=i, device=device, end_s=segment["end_s"])
                    else:
                        self._pending.pop(key, None)
            self._pending_entries = list(self._pending.values())
            self._dirty_records, self._dirty_segments = count, len(segments)
        active = None
        if w.session.running:
            active = dict(time_s=self.time_s(), remaining_s=w.session.remaining_s)
        return dict(measurements=self._pending_entries,
                    calibrations=[key for key, value in w.lab.calibrations.items()
                                  if self._saved_calibrations.get(key) != value],
                    analysis=self.analysis != self._saved_analysis or w.device.id != self._saved_device,
                    settings=self.settings() != self._saved_settings, active_exposure=active)

    def document(self, *, finish=False):
        product = self.work.product()
        end_s = self.measurement_end_s()
        if finish and self.work.session.running and not self.work.session.experiment.outputs:
            row = self.work.session.preview_stop()
            if row is not None:
                # Only the last aggregate can change when settling a partial window.
                segments = product["segments"].copy()
                if segments:
                    segments[-1] = deepcopy(segments[-1])
                _add_windows(segments, [row])
                product = dict(product, segments=segments)
                end_s = row.end_s
        return dict(definition=self.info, time_s=self.time_s(), measurement_end_s=end_s, settings=self.settings(),
                    product=product, device=self.work.device.id, analysis=self.analysis,
                    calibrations={k: asdict(v) for k, v in self.work.lab.calibrations.items()})

    def update_draft(self):
        # New courses keep only this live session's temporary cache. Portable
        # files are explicit downloads; old-course archives remain isolated.
        if self.work.session.experiment.outputs:
            return
        revision = self.revision()
        if self.readonly or self.draft_revision == revision:
            return
        doc = self.document()
        segments = doc["product"]["segments"]
        doc["time_s"] = self.measurement_end_s()
        try:
            self.store.write(self.draft_id, "draft", doc,
                             start=self.changed_start(self.draft_revision[1], self.draft_segments))
        except (OSError, sqlite3.Error) as error:
            self.draft_error = str(error)
            return
        self.draft_error = None
        self.draft_revision, self.draft_segments = revision, len(segments)
        self.recovered_s = doc["time_s"]

    def settings(self):
        return self.archived_settings if self.readonly else dict(self.work.session.settings)

    def time_s(self):
        return self.archive_time if self.readonly else self.work.session.time_s

    def measurement_end_s(self):
        if self.readonly:
            return self.archive_measurement_end
        records = self.work.session.records
        return max(records[-1].end_s if records else 0, getattr(self.work.lab.view, 'saved_end_s', 0))

    def write_cache(self, snapshot):
        """Let other instruments advance while the target snapshot stays immutable."""
        try:
            if self.cache_writer is not None:
                self.cache_writer(snapshot)
        finally:
            self.sync()

    def calibration_context(self):
        w = self.work
        identity = self.saved_selection.get(w.device.id, {}).get('selected')
        if identity:
            saved = self.saved_measurement(identity).snapshot
            return dict(device=w.device.id, selected=None, record_id=identity,
                        settings={key: saved.segments[0].settings[key] for key in w.device.calibration_parameters})
        segments = w.product()["segments"]
        selected = w.lab.selected if w.lab.selected is not None else next(
            (i for i in range(len(segments) - 1, -1, -1) if w.device.id in segments[i]["readings"]), None)
        settings = w.spectrum_settings()
        return dict(device=w.device.id, selected=selected, record_id=None,
                    settings={key: settings[key] for key in w.device.calibration_parameters})

    def check_confirmation(self, data):
        """Reject obsolete exit decisions before advancing the live clock."""
        action = data["action"]
        if action in ("continue", "discard") or (action == "save" and data.get("exit") is True):
            token = data.get("confirmation_id")
            if (not self.frozen or type(token) is not int or token != self.confirmation_id):
                raise ValueError("退出确认已过期，请重新确认。")
        if action == "save" and self.frozen and data.get("exit") is not True:
            raise ValueError("请先完成当前退出确认。")

    def state(self, product_cursor=None):
        w = self.work
        analysis = self.analysis[w.device.id]
        calibration = self.selected_calibration()
        pending = self.unsaved()
        instrument = w.session.instrument(w.device.id) if w.session.experiment.outputs and not self.readonly else None
        instruments = {d.id: asdict(w.session.instrument(d.id)) for d in w.session.experiment.devices} if instrument else {}
        pending_clear = next(((d.id, w.session.pending_clear(d.id)) for d in w.session.experiment.devices
                              if w.session.pending_clear(d.id) is not None), None) if instrument else None
        snapshots = w.session.snapshots
        for item in snapshots[len(self._snapshot_summaries):]:
            device = next(d for d in w.session.experiment.devices if d.id == item.device)
            conditions = dict(device.background_conditions)
            self._snapshot_summaries.append(dict(id=item.id, device=item.device, acquisition=item.acquisition,
                time_s=item.time_s, exposure_s=item.exposure_s, counts=sum(item.counts),
                settings=[dict(s.settings) for i, s in enumerate(item.segments) if i == 0 or s.settings != item.segments[i-1].settings],
                background_eligible=all(all(s.settings.get(k) == v for k, v in conditions.items()) for s in item.segments)))
        package = self.exchange.document
        native_items = {item['document']['snapshot']['id']: item for item in (package or {}).get('items', ())
                        if item['kind'] == 'measurement' and item['source']['package'] == package['id']
                        and item['source']['item'] == item['id']}
        for row in self._snapshot_summaries:
            item = native_items.get(row['id'])
            if item is not None:
                row['item_id'] = item['id']
                row['calibration_id'] = item.get('calibration_id')
        if package:
            for item in package['items'][self._imported_count:]:
                if item['kind'] == 'measurement' and (item['source']['package'] != package['id'] or item['source']['item'] != item['id']):
                    metadata = item['document']['snapshot']
                    self._imported_items.append(dict(id=item['id'], device=metadata['device'], title=item['title'],
                        acquisition=metadata['acquisition'], exposure_s=metadata['exposure_s'], source=item['source'],
                        settings=[s['settings'] for s in item['document']['segments']], calibration_id=item.get('calibration_id')))
            self._imported_count = len(package['items'])
        readout_error = None
        try:
            selected_id = self.saved_selection.get(w.device.id, {}).get('selected')
            readout = (w.readout_snapshot(self.saved_measurement(selected_id).snapshot, *analysis['roi'], calibration=calibration)
                       if selected_id else w.readout(*analysis["roi"]))
        except ValueError as error:
            readout, readout_error = None, analysis_error(error)
        if w.device.kind == "counter":
            key = len(w.session.records), w.device.id, analysis["background"]
            if key != self._counter_analysis_key:
                rows = []
                for i, segment in enumerate(w.product()["segments"]):
                    if w.device.id in segment["readings"]:
                        try:
                            rows.append(dict(index=i, **w.readout_for(i)))
                        except ValueError as error:
                            rows.append(dict(index=i, error=analysis_error(error)))
                self._counter_analysis, self._counter_analysis_key = rows, key
        flow = w.session.particle_flow
        result = dict(id=self.id, experiment=w.current, definition=self.info,
                    seed=w.seed, settings=self.settings(), time_s=self.time_s(),
                    running=instrument.running if instrument else w.session.running,
                    any_running=w.session.running, clock_running=w.session.clock_running,
                    output_enabled=dict(w.session.output_enabled),
                    instrument=asdict(instrument) if instrument else None,
                    instruments=instruments,
                    particle_flow=({key: flow[key] for key in ('thickness_um', 'areal_density_g_cm2') if key in flow}
                                   if flow is not None else None),
                    counter_windows={d.id: [window_state(row) for row in w.session.instrument_windows(d.id)]
                                     for d in w.session.experiment.devices if d.kind == 'counter'} if instrument else {},
                    snapshots=self._snapshot_summaries,
                    imported_items=self._imported_items,
                    cached_calibrations=[dict(id=item['id'], device=item['document']['device'], title=item['title'])
                                         for item in (self.exchange.document or {}).get('items', ()) if item['kind'] == 'calibration'],
                    gates={d.id: (w.session.instrument(d.id).running if w.session.experiment.outputs else w.session.running)
                           for d in w.session.experiment.devices},
                    clear_confirmation=(dict(device=pending_clear[0], token=pending_clear[1].token,
                        exposure_s=pending_clear[1].snapshot.exposure_s if pending_clear[1].snapshot else 0)
                        if pending_clear else None),
                    exposure_s=instrument.exposure_s if instrument else None,
                    paused=w.paused, frozen=self.frozen,
                    active_acquisition=(instrument.acquisition if instrument.running else None) if instrument else w.session.active_acquisition,
                    confirmation_id=self.confirmation_id,
                    speed=w.speed, remaining_s=instrument.remaining_s if instrument else w.session.remaining_s, device=w.device.id,
                    selected=w.lab.selected, analysis=analysis,
                    selected_item_id=self.saved_selection.get(w.device.id, {}).get('selected'),
                    reference_item_id=self.saved_selection.get(w.device.id, {}).get('reference'),
                    selected_observation=self.saved_observation('selected'), reference_observation=self.saved_observation('reference'),
                    saved_measurements=[dict(id=item['id'], device=item['document']['snapshot']['device'], title=item['title'],
                        exposure_s=item['document']['snapshot']['exposure_s'], settings=[s['settings'] for s in item['document']['segments']],
                        calibration_id=item.get('calibration_id')) for item in (package or {}).get('items', ()) if item['kind'] == 'measurement'],
                    spectrum_settings=dict(w.spectrum_settings()),
                    calibration=asdict(calibration) if calibration else None,
                    reference_calibration=(asdict(self.reference_calibration()) if self.reference_calibration() else None),
                    calibration_context=self.calibration_context(),
                    calibrated_devices=list(w.lab.calibrations),
                    readout=readout, readout_error=readout_error,
                    counter_analysis=self._counter_analysis if w.device.kind == "counter" else [], readonly=self.readonly,
                    portable_loaded=self.portable_loaded,
                    portable_unresolved=getattr(self, 'portable_unresolved', {}),
                    dirty=any(pending.values()), unsaved=pending, recovered_s=self.recovered_s,
                    draft_error=self.draft_error,
                    export_notice="已生成下载；浏览器未确认文件保存成功，未保存状态仍保留。")
        product = w.product()
        result["measurement_end_s"] = self.measurement_end_s()
        count, length = len(w.session.records), len(product["segments"])
        product_identity = self.id if not self.product_generation else f'{self.id}.{self.product_generation}'
        result["product_cursor"] = f"{product_identity}:{count}:{length}"
        try:
            identity, old_count, old_length = product_cursor.split(":")
            old_count, old_length = int(old_count), int(old_length)
            valid = identity == product_identity and 0 <= old_count <= count and 0 <= old_length <= length
        except (AttributeError, TypeError, ValueError):
            valid = False
        if valid:
            start = self.changed_start(old_count, old_length)
            result["product_delta"] = dict(start=start, segments=product["segments"][start:])
        else:
            result["product"] = product
        return result

    @classmethod
    def read(cls, identifier, store, clock):
        doc = store.read(identifier)
        product, info = doc["product"], doc["definition"]
        lab = cls(archived_definition(info), info, product["seed"], store, clock)
        # A viewer owns fresh target ids; its source may still have a live writer.
        lab.work.lab.view = ArchivedView(product)
        lab.archive_time = doc["time_s"]
        lab.archive_measurement_end = doc.get("measurement_end_s", max(
            (s["end_s"] for s in product["segments"]), default=0))
        lab.archived_settings = doc["settings"]
        for key, value in lab.archived_settings.items():
            lab.work.session.set(key, value)
        lab.analysis = doc["analysis"]
        lab.work.lab.calibrations = {k: Calibration(**v) for k, v in doc["calibrations"].items()}
        lab.bind(doc["device"])
        lab.mark_saved()
        if identifier.startswith("draft-"):
            lab.source = ("draft", identifier)
            lab.recovered_s = lab.archive_time
            lab.saved_revision = None
            lab._saved_ends = {}
            lab._saved_analysis = None
            lab._saved_calibrations = {}
            lab._dirty_records = -1
            lab._dirty_segments = 0
            lab._saved_settings = None
        else:
            lab.source = ("archive", identifier)
        return lab

    def bind(self, device, *, restore_calibration=True):
        self.work.bind_device(device)
        analysis = self.analysis[device]
        self.work.select(analysis["selected"])
        self.work.set_background(analysis["background"])
        if restore_calibration:
            self.select_saved_calibration()

    def saved_item_calibration(self, index):
        indices = getattr(self.work.lab.view, 'item_indices', {})
        identity = next((identity for identity, rows in indices.items() if index in rows), None)
        items = (self.exchange.document or {}).get('items', ())
        item = next((item for item in items if item['id'] == identity), None)
        saved = next((entry for entry in items if item and entry['id'] == item.get('calibration_id')), None)
        return item, Calibration.from_document(saved['document']) if saved else None

    def saved_measurement(self, identity, device=None):
        if identity not in self._decoded_items:
            self._decoded_items[identity] = decode_measurement(self.exchange.document, self.work.session.experiment,
                                                              device or self.work.device.id, identity)
        decoded = self._decoded_items[identity]
        if decoded.snapshot.device != (device or self.work.device.id):
            raise ValueError('所选记录不属于当前仪器。')
        return decoded

    def selected_calibration(self):
        identity = self.saved_selection.get(self.work.device.id, {}).get('selected')
        if not identity:
            return self.work.active_calibration()
        calibration = self.work.lab.calibrations.get(self.work.device.id)
        return calibration if calibration and all(calibration.applies_to(row.settings)
            for row in self.saved_measurement(identity).snapshot.segments) else None

    def saved_observation(self, key):
        identity = self.saved_selection.get(self.work.device.id, {}).get(key)
        if identity is None:
            return None
        decoded = self.saved_measurement(identity)
        item = next(item for item in self.exchange.document['items'] if item['id'] == identity)
        return dict(id=identity, device=decoded.snapshot.device, title=decoded.title,
                    counts=decoded.snapshot.counts, exposure_s=decoded.snapshot.exposure_s,
                    segments=item['document']['segments'], calibration_id=item.get('calibration_id'))

    def select_saved_item(self, key, identity):
        if identity is not None:
            self.saved_measurement(identity)
        self.clear_portable_reference(self.work.device.id, key)
        if identity is not None:
            self.saved_selection.setdefault(self.work.device.id, {})[key] = identity
            self.saved_analysis.setdefault(self.work.device.id, {})[key] = identity
        self.edits += 1

    def reference_calibration(self):
        identity = self.saved_selection.get(self.work.device.id, {}).get('reference')
        if identity:
            return self.saved_measurement(identity).calibration
        index = self.analysis[self.work.device.id]['reference']
        if index is None:
            return None
        item, calibration = self.saved_item_calibration(index)
        if item is None:
            calibration = self.work.lab.calibrations.get(self.work.device.id)
        settings = self.work.product()['segments'][index]['settings']
        return calibration if calibration and calibration.applies_to(settings) else None

    def select_saved_calibration(self):
        device = self.work.device.id
        identity = self.saved_selection.get(device, {}).get('selected')
        if identity:
            item, calibration = True, self.saved_measurement(identity).calibration
        else:
            item, calibration = self.saved_item_calibration(self.work.lab.selected)
        if item is not None:
            if device not in self._saved_calibration_devices:
                self._live_calibrations[device] = self.work.lab.calibrations.get(device)
            self._saved_calibration_devices.add(device)
        elif device in self._saved_calibration_devices:
            calibration = self._live_calibrations.get(device)
            self._saved_calibration_devices.remove(device)
        else:
            return
        if calibration is None:
            self.work.lab.calibrations.pop(device, None)
        else:
            self.work.lab.calibrations[device] = calibration

    def index(self, index, device=None):
        segments = self.work.product()["segments"]
        if index is not None and (type(index) is not int or not 0 <= index < len(segments)):
            raise ValueError("请先选择已采集的测量段。")
        if index is not None and (device or self.work.device.id) not in segments[index]["readings"]:
            raise ValueError("所选测量段不属于当前仪器。")
        return index

    def _check_device_target(self, data):
        """Bind instrument-local commands to the device shown by their caller."""
        w = self.work
        if "device" in data and data["device"] != w.device.id:
            raise ValueError("所用设备已改变，请重新查看仪器后操作。")
        if "device" not in data and len(w.session.experiment.devices) > 1:
            raise ValueError("请明确所用设备后重新操作。")

    def instrument_group(self, component):
        part = next((part for part in self.work.session.experiment.components if part.id == component), None)
        if part is None or part.kind != 'instrument' or not part.devices:
            raise ValueError('请选择包含多个窗的仪器。')
        return part.devices

    def change_analysis(self, data):
        self._check_device_target(data)
        w = self.work
        current = self.analysis[w.device.id]
        updates = {}
        for key in ("roi", "reference", "background", "energy_axis", "rate_axis"):
            if key not in data:
                continue
            value = data[key]
            if key == "roi":
                if (not isinstance(value, list) or len(value) != 2 or
                        any(type(i) is not int for i in value) or
                        not 0 <= value[0] <= value[1] < w.device.channels):
                    raise ValueError("ROI 必须位于当前仪器的有效道址内。")
            elif key in ("reference", "background"):
                self.index(value)
                if key == "background" and value is not None:
                    if w.device.kind != "counter":
                        raise ValueError("只有计数器可选计数参考。")
                    conditions = dict(w.device.background_conditions)
                    settings = w.product()["segments"][value]["settings"]
                    if any(settings.get(k) != v for k, v in conditions.items()):
                        raise ValueError("所选记录不符合该计数器声明的本底工况。")
            elif type(value) is not bool:
                raise ValueError("坐标轴选择无效。")
            updates[key] = value
        for key in updates:
            self.clear_portable_reference(w.device.id, key)
        if any(current[k] != v for k, v in updates.items()):
            current.update(updates)
            w.set_background(current["background"])
            self.edits += 1

    def clear_portable_reference(self, device, key):
        """An explicit choice replaces an unresolved UUID, including choosing none."""
        getattr(self, 'portable_preserved_analysis', {}).get(device, {}).pop(key, None)
        getattr(self, 'portable_unresolved', {}).get(device, {}).pop(key, None)
        self.saved_selection.get(device, {}).pop(key, None)
        self.saved_analysis.get(device, {}).pop(key, None)

    def act(self, data):
        """Apply one action, settling its clock only after exit-round validation."""
        self.check_confirmation(data)
        if data['action'] == 'stop_group':
            devices = self.instrument_group(data['component'])
            cycles = data.get('gate_cycles')
            if (not isinstance(cycles, dict) or set(cycles) != set(devices)
                    or any((cycles[device] is not None and type(cycles[device]) is not int)
                           or cycles[device] != self.work.session.instrument(device).cycle for device in devices)):
                raise ValueError('采集门已改变或已关闭，请重新查看计数器后操作。')
        if data['action'] in ('select', 'analysis') and any(
                data.get(key) is not None for key in ('index', 'reference', 'background')):
            cursor = data.get('product_cursor')
            identity = self.id if not self.product_generation else f'{self.id}.{self.product_generation}'
            if cursor is not None and cursor.split(':', 1)[0] != identity:
                raise ValueError('记录列表已改变，请重新选择所需记录。')
        if data["action"] == "stop":
            if self.work.session.experiment.outputs:
                self._check_device_target(data)
                target = self.work.session.instrument(self.work.device.id)
                active_acquisition = target.acquisition if target.running else None
                if type(data.get("cycle")) is not int or data["cycle"] != target.cycle:
                    raise ValueError("采集门已改变或已关闭，请重新查看仪器后操作。")
            else:
                active_acquisition = self.work.session.active_acquisition
            acquisition = data.get("acquisition")
            if type(acquisition) is not int or acquisition != active_acquisition:
                raise ValueError("采集轮次已改变或已结束，请重新查看采集门后操作。")
        self.sync()
        action, w = data["action"], self.work
        if self.frozen and action not in ("freeze", "continue", "suspend", "save", "discard"):
            raise ValueError("先返回实验，再执行此操作。")
        if self.readonly and action in ("start", "stop", "configure", "speed", "pause", "output", "snapshot", "begin_clear", "finish_clear", "instrument_config", "cache_calibration", 'start_group', 'stop_group', 'instrument_group_config', 'window_config', 'load_measurement'):
            raise ValueError("已保存的实验只支持查看和分析。")
        if action in ("calibrate", "load_calibration", "cache_calibration"):
            if data.get("calibration_context") != self.calibration_context():
                raise ValueError("刻度所用设备、测量记录或适用工况已改变，请重新查看谱后操作。")
        if action == "freeze":
            if not self.frozen:
                self._confirmation_serial += 1
                self.confirmation_id = self._confirmation_serial
            self.frozen = True
        elif action == "suspend":
            # A page leaving checkpoints completed windows, not the shared clock.
            pass
        elif action == "continue":
            self.frozen = False
            self.confirmation_id = None
            self.last_tick = self.clock()
        elif action == "configure":
            old = dict(w.session.settings)
            w.configure(data["values"])
            if old != w.session.settings:
                self.edits += 1
        elif action == "start":
            if w.session.experiment.outputs:
                self._check_device_target(data)
                w.start(data.get("duration"), device=w.device.id,
                        count_limit=data.get("count_limit"), window_s=data.get("window_s"))
                w.select(None)
                self.analysis[w.device.id]["selected"] = None
                self.clear_portable_reference(w.device.id, 'selected')
                getattr(self, 'portable_default_selection', {}).pop(w.device.id, None)
                self.select_saved_calibration()
            else:
                w.start(data.get("duration"))
        elif action in ('start_group', 'stop_group', 'instrument_group_config'):
            devices = self.instrument_group(data['component'])
            if action == 'start_group':
                w.session.start_group(devices)
                for device in devices:
                    self.clear_portable_reference(device, 'selected')
                    self.analysis[device]['selected'] = None
                w.select(None)
                self.select_saved_calibration()
            elif action == 'stop_group':
                w.session.stop_group(devices)
            else:
                w.session.configure_group(devices, **{key: data[key] for key in ('duration_s', 'count_limit') if key in data})
        elif action == 'window_config':
            devices = self.instrument_group(data['component'])
            if data['device'] not in devices:
                raise ValueError('所选窗不属于该计数器。')
            w.session.configure_acquisition(data['device'], window_s=data['window_s'])
        elif action == "stop":
            w.stop(device=w.device.id if w.session.experiment.outputs else None)
        elif action == "output":
            w.set_output(data["output"], data["enabled"])
            self.edits += 1
        elif action == "snapshot":
            self._check_device_target(data)
            snapshot = w.snapshot(writer=self.write_cache)
            self.bind_saved_calibration(snapshot)
            self.edits += 1
        elif action == "cache_calibration":
            self._check_device_target(data)
            self.cache_calibration()
            self.edits += 1
        elif action == "import_item":
            from .web_import import apply_import
            apply_import(self, data['token'], data['item_id'])
            self.edits += 1
        elif action == 'load_measurement':
            from .web_measurement import load_measurement
            load_measurement(self, data['token'], data['item_id'], data.get('overwrite', False))
        elif action == "instrument_config":
            self._check_device_target(data)
            w.configure_acquisition(**{key: data[key] for key in ('duration_s', 'count_limit', 'window_s') if key in data})
            self.edits += 1
        elif action == "begin_clear":
            self._check_device_target(data)
            request = w.begin_clear()
            if request.snapshot is None:
                w.finish_clear(request.token, "discard")
            else:
                self._clear_requests[w.device.id] = request
            self.edits += 1
        elif action == "finish_clear":
            device = data["device"]
            if device not in self.analysis:
                raise ValueError("请选择有效的设备。")
            try:
                snapshot = w.finish_clear(data["token"], data["choice"], device=device, writer=self.write_cache)
                if data['choice'] == 'save' and snapshot is not None:
                    self.bind_saved_calibration(snapshot)
            finally:
                # A failed cache write restores this instrument, just like cancel.
                if not w.session.instrument(device).clearing:
                    self._clear_requests.pop(device, None)
            self.edits += 1
        elif action == "speed":
            w.set_speed(data["speed"])
        elif action == "pause":
            if type(data["paused"]) is not bool:
                raise ValueError("暂停操作无效。")
            w.paused = data["paused"]
        elif action == "device":
            if data["device"] != w.device.id:
                self.bind(data["device"])
                self.edits += 1
        elif action == "select":
            self._check_device_target(data)
            if 'item_id' in data and data['item_id'] is not None:
                self.select_saved_item('selected', data['item_id'])
                w.select(None)
                self.analysis[w.device.id]['selected'] = None
                self.select_saved_calibration()
                return False
            index = self.index(data["index"])
            getattr(self, 'portable_default_selection', {}).pop(w.device.id, None)
            self.clear_portable_reference(w.device.id, 'selected')
            if index != w.lab.selected:
                w.select(index)
                self.analysis[w.device.id]["selected"] = index
                self.edits += 1
            self.select_saved_calibration()
        elif action == "analysis":
            if 'reference_item_id' in data:
                self.select_saved_item('reference', data['reference_item_id'])
                self.analysis[w.device.id]['reference'] = None
            self.change_analysis(data)
        elif action == "calibrate":
            identity = self.saved_selection.get(w.device.id, {}).get('selected')
            if identity:
                w.calibrate_snapshot(self.saved_measurement(identity).snapshot, *data['points'])
            else:
                w.calibrate(*data["points"])
            self.edits += 1
        elif action == "load_calibration":
            document = data["calibration"]
            if document.get('format') == 'nuclemu.item/1':
                bundle = load_item(json.dumps(document).encode('utf-8'))
                if bundle['items'][0]['kind'] != 'calibration':
                    raise ValueError("请选择一份已保存的刻度记录。")
                document = bundle['items'][0]['document']
            identity = self.saved_selection.get(w.device.id, {}).get('selected')
            if identity:
                w.apply_snapshot_calibration(self.saved_measurement(identity).snapshot, Calibration.from_document(document))
            else:
                w.apply_calibration(Calibration.from_document(document))
            self.edits += 1
        elif action == "save":
            if w.session.experiment.outputs and not self.readonly:
                raise ValueError("请下载整场 .nuclemu 文件；仪器读数请保存到本场缓存。")
            leave = data.get("exit", False)
            if type(leave) is not bool:
                raise ValueError("退出选项无效。")
            try:
                document = self.document(finish=leave)
                self.store.write(self.archive_id, "archive", document,
                                 remove=self.draft_id if not self.readonly else None)
            finally:
                # Legacy exit handling excludes disk I/O; independent live gates keep time.
                if leave or not w.session.experiment.outputs:
                    self.last_tick = self.clock()
            self.mark_saved(document["product"])
            self.draft_revision = self.revision()
            self.draft_segments = 0
            self.recovered_s = None
            self.draft_error = None
            if leave:
                self.confirmation_id = None
                return True
        elif action == "discard":
            if not self.readonly and not w.session.experiment.outputs:
                self.store.remove(self.draft_id)
            self.confirmation_id = None
            return True
        else:
            raise ValueError("未知的工作台操作。")
        return False

    def export(self, data):
        w, fmt = self.work, data["format"]
        device = data["device"]
        if device not in self.analysis or fmt not in ("json", "csv"):
            raise ValueError("请选择有效的设备和格式。")
        kind = data.get("kind", "measurement")
        calibration = w.lab.calibrations.get(device)
        if kind == "calibration":
            if fmt != "json" or calibration is None:
                raise ValueError("请先建立刻度并选择 JSON。")
            return (json.dumps(calibration.document(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if kind != "measurement":
            raise ValueError("未知的测量产品。")
        product = w.product()
        indices = data["indices"]
        if (not isinstance(indices, list) or not indices
                or any(i is None for i in indices) or len(set(indices)) != len(indices)):
            raise ValueError("请选择不重复的测量段。")
        selected = [product["segments"][self.index(i, device)] for i in indices]
        stream = StringIO(newline="")
        write_product(stream, fmt, dict(product, segments=selected), device, calibration)
        return stream.getvalue().encode("utf-8")


class Application:
    def __init__(self, definitions, directory, clock=monotonic):
        self.definitions = definitions
        self.store = ArchiveStore(directory)
        self.clock = clock
        self.lab = None

    def catalog(self, *, include_history=True):
        rows = self.store.list() if include_history else []
        drafts = [r for r in rows if r["kind"] == "draft"]
        return dict(experiments=[describe(e) for e in self.definitions.values()],
                    archives=[r for r in rows if r["kind"] == "archive"],
                    drafts=drafts, draft=drafts[0] if drafts else None)

    def open(self, data):
        if data.get("draft"):
            identifier = data["draft"]
            if identifier is True:
                draft = self.catalog()["draft"]
                if draft is None:
                    raise ValueError("没有恢复草稿。")
                identifier = draft["id"]
            source = ("draft", identifier)
        elif "archive" in data:
            source = ("archive", data["archive"])
        else:
            source = None
        if source is not None and (not isinstance(source[1], str)
                or (source[0] == "draft") != source[1].startswith("draft-")):
            raise ValueError("实验记录与恢复草稿不能混用。")
        if self.lab is not None:
            same_archive = source is not None and self.lab.source == source
            same_live = (source is None and not self.lab.readonly
                         and data.get("experiment") == self.lab.work.current
                         and ("seed" not in data or (type(data["seed"]) is int
                              and data["seed"] == self.lab.work.seed)))
            if same_archive or same_live:
                return self.state(session=self.lab.id)
            raise ValueError("请先从当前实验退出。")
        if source is not None and source[0] == "draft":
            self.lab = WebLab.read(identifier, self.store, self.clock)
        elif "archive" in data:
            self.lab = WebLab.read(data["archive"], self.store, self.clock)
        else:
            e = self.definitions[data["experiment"]]
            self.lab = WebLab(e, describe(e), data.get("seed", 0), self.store, self.clock)
        return self.lab.state()

    def state(self, session=None, product_cursor=None):
        if session is not None and (self.lab is None or session != self.lab.id):
            raise ValueError("会话已结束，请返回目录。")
        if self.lab is not None:
            self.lab.sync()
            self.lab.update_draft()
            return self.lab.state(product_cursor)
        return None

    def request(self, path, data):
        if path == "/api/open":
            return self.open(data)
        if path == "/api/open_package":
            if self.lab is not None:
                raise ValueError("请先退出当前实验，再打开实验文件。")
            from .web_portable import open_portable
            self.lab = open_portable(b64decode(data["file"], validate=True), self.definitions, self.store, self.clock)
            return self.lab.state()
        if self.lab is None or data.get("session") != self.lab.id:
            raise ValueError("会话已结束，请返回目录。")
        if path == '/api/replace_package':
            self.lab.check_confirmation(dict(action='discard', confirmation_id=data.get('confirmation_id')))
            from .web_portable import open_portable
            replacement = open_portable(b64decode(data['file'], validate=True), self.definitions, self.store, self.clock)
            self.lab = replacement
            return replacement.state()
        if path == "/api/action":
            if self.lab.act(data):
                self.lab = None
                return None
            self.lab.update_draft()
            return self.lab.state(data.get("product_cursor"))
        self.lab.sync()
        if path == '/api/inspect_import':
            from .web_import import inspect_import
            return inspect_import(self.lab, b64decode(data['file'], validate=True))
        if path == '/api/inspect_measurement':
            from .web_measurement import inspect_measurement
            return inspect_measurement(self.lab, data['device'], b64decode(data['file'], validate=True) if 'file' in data else None)
        if path in ("/api/export", "/api/download"):
            self.lab.update_draft()
        if path == "/api/export":
            return self.lab.export(data)
        if path == "/api/download":
            if data.get("scope") == "experiment":
                return self.lab.portable_download()
            if "snapshots" in data:
                return self.lab.portable_download(data["snapshots"])
            return make_download(self.lab, data["products"])
        raise ValueError("未知请求。")
