"""Server-owned clock, measurements, analysis selections and archive transactions."""

from copy import deepcopy
from dataclasses import asdict
from io import StringIO
import json
import sqlite3
from time import monotonic
from uuid import uuid4

from .catalog import describe
from .core import Device, Experiment, Parameter
from .workbench import Workbench
from .results import Calibration, _add_windows, write_product
from .web_download import make_download
from .web_store import ArchiveStore


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
                      tuple(Device(**d) for d in info["devices"]), unavailable)


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
        self._saved_ends = {(i, d.id): s["end_s"] for i, s in enumerate(segments)
                            for d in self.work.session.experiment.devices}
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
        count = len(w.session.records)
        if count != self._dirty_records:
            segments = w.product()["segments"]
            for i in range(max(0, self._dirty_segments - 1), len(segments)):
                segment = segments[i]
                for d in w.session.experiment.devices:
                    key = i, d.id
                    if self._saved_ends.get(key) != segment["end_s"]:
                        self._pending[key] = dict(index=i, device=d.id, end_s=segment["end_s"])
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
        if finish and self.work.session.running:
            row = self.work.session.preview_stop()
            if row is not None:
                # Only the last aggregate can change when settling a partial window.
                segments = product["segments"].copy()
                if segments:
                    segments[-1] = deepcopy(segments[-1])
                _add_windows(segments, [row])
                product = dict(product, segments=segments)
        end_s = product["segments"][-1]["end_s"] if product["segments"] else 0
        return dict(definition=self.info, time_s=self.time_s(), measurement_end_s=end_s, settings=self.settings(),
                    product=product, device=self.work.device.id, analysis=self.analysis,
                    calibrations={k: asdict(v) for k, v in self.work.lab.calibrations.items()})

    def update_draft(self):
        revision = self.revision()
        if self.readonly or self.draft_revision == revision:
            return
        doc = self.document()
        segments = doc["product"]["segments"]
        doc["time_s"] = segments[-1]["end_s"] if segments else 0
        try:
            self.store.write(self.draft_id, "draft", doc, start=max(0, self.draft_segments - 1))
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

    def calibration_context(self):
        w = self.work
        segments = w.product()["segments"]
        selected = w.lab.selected if w.lab.selected is not None else (len(segments) - 1 if segments else None)
        settings = w.spectrum_settings()
        return dict(device=w.device.id, selected=selected,
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
        calibration = w.active_calibration()
        pending = self.unsaved()
        result = dict(id=self.id, experiment=w.current, definition=self.info,
                    seed=w.seed, settings=self.settings(), time_s=self.time_s(),
                    running=w.session.running, paused=w.paused, frozen=self.frozen,
                    active_acquisition=w.session.active_acquisition,
                    confirmation_id=self.confirmation_id,
                    speed=w.speed, remaining_s=w.session.remaining_s, device=w.device.id,
                    selected=w.lab.selected, analysis=analysis,
                    spectrum_settings=dict(w.spectrum_settings()),
                    calibration=asdict(calibration) if calibration else None,
                    calibration_context=self.calibration_context(),
                    calibrated_devices=list(w.lab.calibrations),
                    readout=w.readout(*analysis["roi"]), readonly=self.readonly,
                    dirty=any(pending.values()), unsaved=pending, recovered_s=self.recovered_s,
                    draft_error=self.draft_error,
                    export_notice="已生成下载；浏览器未确认文件保存成功，未保存状态仍保留。")
        product = w.product()
        result["measurement_end_s"] = product["segments"][-1]["end_s"] if product["segments"] else 0
        count, length = len(w.session.records), len(product["segments"])
        result["product_cursor"] = f"{self.id}:{count}:{length}"
        try:
            identity, old_count, old_length = product_cursor.split(":")
            old_count, old_length = int(old_count), int(old_length)
            valid = identity == self.id and 0 <= old_count <= count and 0 <= old_length <= length
        except (AttributeError, TypeError, ValueError):
            valid = False
        if valid:
            start = length if (old_count, old_length) == (count, length) else max(0, old_length - 1)
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

    def bind(self, device):
        self.work.bind_device(device)
        analysis = self.analysis[device]
        self.work.select(analysis["selected"])
        self.work.set_background(analysis["background"])

    def index(self, index):
        if index is not None and (type(index) is not int or not 0 <= index < len(self.work.product()["segments"])):
            raise ValueError("请先选择已采集的测量段。")
        return index

    def _check_device_target(self, data):
        """Bind instrument-local commands to the device shown by their caller."""
        w = self.work
        if "device" in data and data["device"] != w.device.id:
            raise ValueError("所用设备已改变，请重新查看仪器后操作。")
        if "device" not in data and len(w.session.experiment.devices) > 1:
            raise ValueError("请明确所用设备后重新操作。")

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
        if any(current[k] != v for k, v in updates.items()):
            current.update(updates)
            w.set_background(current["background"])
            self.edits += 1

    def act(self, data):
        """Apply one action, settling its clock only after exit-round validation."""
        self.check_confirmation(data)
        if data["action"] == "stop":
            acquisition = data.get("acquisition")
            if type(acquisition) is not int or acquisition != self.work.session.active_acquisition:
                raise ValueError("采集轮次已改变或已结束，请重新查看采集门后操作。")
        self.sync()
        action, w = data["action"], self.work
        if self.frozen and action not in ("freeze", "continue", "suspend", "save", "discard"):
            raise ValueError("先返回实验，再执行此操作。")
        if self.readonly and action in ("start", "stop", "configure", "speed", "pause"):
            raise ValueError("已保存的实验只支持查看和分析。")
        if action in ("calibrate", "load_calibration"):
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
            w.start(data.get("duration"))
        elif action == "stop":
            w.stop()
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
            index = self.index(data["index"])
            if index != w.lab.selected:
                w.select(index)
                self.analysis[w.device.id]["selected"] = index
                self.edits += 1
        elif action == "analysis":
            self.change_analysis(data)
        elif action == "calibrate":
            w.calibrate(*data["points"])
            self.edits += 1
        elif action == "load_calibration":
            w.apply_calibration(Calibration.from_document(data["calibration"]))
            self.edits += 1
        elif action == "save":
            leave = data.get("exit", False)
            if type(leave) is not bool:
                raise ValueError("退出选项无效。")
            try:
                document = self.document(finish=leave)
                self.store.write(self.archive_id, "archive", document,
                                 remove=self.draft_id if not self.readonly else None)
            finally:
                # Confirmation and disk I/O are outside laboratory exposure.
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
            if not self.readonly:
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
        selected = [product["segments"][self.index(i)] for i in indices]
        stream = StringIO(newline="")
        write_product(stream, fmt, dict(product, segments=selected), device, calibration)
        return stream.getvalue().encode("utf-8")


class Application:
    def __init__(self, definitions, directory, clock=monotonic):
        self.definitions = definitions
        self.store = ArchiveStore(directory)
        self.clock = clock
        self.lab = None

    def catalog(self):
        rows = self.store.list()
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
        if self.lab is None or data.get("session") != self.lab.id:
            raise ValueError("会话已结束，请返回目录。")
        if path == "/api/action":
            if self.lab.act(data):
                self.lab = None
                return None
            self.lab.update_draft()
            return self.lab.state(data.get("product_cursor"))
        self.lab.sync()
        if path in ("/api/export", "/api/download"):
            self.lab.update_draft()
        if path == "/api/export":
            return self.lab.export(data)
        if path == "/api/download":
            return make_download(self.lab, data["products"])
        raise ValueError("未知请求。")
