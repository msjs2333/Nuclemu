"""Launch the browser workbench and retain the original Tk embedding API."""

from __future__ import annotations

from time import monotonic

from .workbench import Workbench


class TkWorkbench:
    """One native window; plots use Canvas and require no third-party packages."""

    def __init__(self, root, controller=None, *, paths=(), clock=monotonic):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.root = root
        self.controller = controller or Workbench(paths)
        self.clock = clock
        self.last_tick = clock()
        self.after_id = None
        self.render_key = None
        self.dialog_depth = 0
        self.rois = {}
        self.roi = (0, self.controller.device.channels - 1)
        root.title("Nuclemu — A Virtual Nuclear Physics Lab")
        root.geometry("1180x780")
        root.minsize(980, 680)
        root.protocol("WM_DELETE_WINDOW", self.close)
        outer = ttk.Frame(root, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Nuclemu · 核物理实验台", font=("", 19, "bold")).pack(anchor="w")
        ttk.Label(outer, text="A Virtual Nuclear Physics Lab").pack(anchor="w", pady=(0, 8))
        bar = ttk.Frame(outer)
        bar.pack(fill="x")
        ttk.Label(bar, text="实验").pack(side="left")
        self.experiment_ids = list(self.controller.definitions)
        self.experiment_box = ttk.Combobox(bar, state="readonly", width=44,
            values=[f"{e.title} [{e.id}]" for e in self.controller.definitions.values()])
        self.experiment_box.pack(side="left", padx=6)
        self.experiment_box.bind("<<ComboboxSelected>>", self.change_experiment)
        self.pause = tk.BooleanVar(value=False)
        self.pause_button = ttk.Checkbutton(bar, text="暂停仿真时间", variable=self.pause,
                        command=lambda: self.act(self.change_pause))
        self.pause_button.pack(side="left", padx=8)
        ttk.Label(bar, text="速度 ×").pack(side="left")
        self.speed = tk.StringVar(value="1")
        speed_box = ttk.Combobox(bar, textvariable=self.speed, values=("0.25", "1", "2", "5", "10"), width=5)
        speed_box.pack(side="left")
        speed_box.bind("<<ComboboxSelected>>", lambda event: self.act(self.change_clock))
        speed_box.bind("<Return>", lambda event: self.act(self.change_clock))
        self.status = tk.StringVar()
        ttk.Label(outer, textvariable=self.status).pack(anchor="w", pady=8)
        body = ttk.Panedwindow(outer, orient="horizontal")
        body.pack(fill="both", expand=True)
        left, right = ttk.Frame(body, width=330), ttk.Frame(body)
        body.add(left, weight=0)
        body.add(right, weight=1)
        self.description = ttk.Label(left, wraplength=310, justify="left")
        self.description.pack(anchor="w", pady=(0, 8))
        self.parameters = ttk.LabelFrame(left, text="装置参数", padding=8)
        self.parameters.pack(fill="x")
        self.parameter_vars = {}
        acquisition = ttk.LabelFrame(left, text="采集门", padding=8)
        acquisition.pack(fill="x", pady=8)
        self.mode = tk.StringVar(value="手动")
        ttk.Combobox(acquisition, state="readonly", textvariable=self.mode,
                     values=("手动", "定时"), width=8).grid(row=0, column=0)
        self.duration = tk.StringVar(value="10")
        ttk.Entry(acquisition, textvariable=self.duration, width=8).grid(row=0, column=1, padx=4)
        ttk.Label(acquisition, text="仿真秒（定时）").grid(row=0, column=2)
        self.start_button = ttk.Button(acquisition, text="开始采集", command=lambda: self.act(self.start))
        self.start_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.stop_button = ttk.Button(acquisition, text="停止", command=lambda: self.act(self.stop))
        self.stop_button.grid(row=1, column=2, sticky="ew", pady=(8, 0))
        ttk.Label(left, text="历史段（最新随采集更新）").pack(anchor="w")
        self.history = tk.Listbox(left, height=8, exportselection=False)
        self.history.pack(fill="both", expand=True)
        self.history.bind("<<ListboxSelect>>", self.select_history)
        ttk.Button(left, text="跟随最新段", command=lambda: self.act(self.follow_latest)).pack(fill="x", pady=3)
        ttk.Button(left, text="导出所选段…", command=lambda: self.act(self.export)).pack(fill="x", pady=3)
        ttk.Button(left, text="导出当前设备全部段…", command=lambda: self.act(lambda: self.export(True))).pack(fill="x", pady=3)
        self.device_box = ttk.Combobox(right, state="readonly")
        self.device_box.pack(fill="x")
        self.device_box.bind("<<ComboboxSelected>>", self.change_device)
        self.reading = tk.StringVar(value="等待采集")
        ttk.Label(right, textvariable=self.reading, font=("", 13), wraplength=760,
                  justify="left").pack(anchor="w", pady=8)
        self.plot_area = ttk.Frame(right)
        self.plot_area.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.plot_area, background="#101c2b", height=280, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda event: self.draw())
        self.counter_table_frame = ttk.Frame(self.plot_area)
        columns = ("segment", "settings", "counts", "exposure", "rate")
        self.counter_table = ttk.Treeview(self.counter_table_frame, columns=columns,
                                          show="headings", selectmode="browse")
        for name, heading, width in zip(columns,
                ("段", "工况", "计数", "曝光 / s", "计数率 / s⁻¹"), (45, 310, 80, 90, 115)):
            self.counter_table.heading(name, text=heading)
            self.counter_table.column(name, width=width, minwidth=width, stretch=name == "settings")
        self.counter_table.grid(row=0, column=0, sticky="nsew")
        for orient, side, command in (("vertical", "y", self.counter_table.yview),
                                      ("horizontal", "x", self.counter_table.xview)):
            scrollbar = ttk.Scrollbar(self.counter_table_frame, orient=orient, command=command)
            scrollbar.grid(row=0 if side == "y" else 1, column=1 if side == "y" else 0,
                           sticky="ns" if side == "y" else "ew")
            self.counter_table.configure(**{side + "scrollcommand": scrollbar.set})
        self.counter_table_frame.rowconfigure(0, weight=1)
        self.counter_table_frame.columnconfigure(0, weight=1)
        self.counter_table.bind("<<TreeviewSelect>>", self.select_counter_row)
        self.spectrum_tools = ttk.Frame(right)
        self.roi_first, self.roi_last = tk.StringVar(value="0"), tk.StringVar(value="1023")
        roi = ttk.Frame(self.spectrum_tools)
        roi.pack(fill="x", pady=5)
        ttk.Label(roi, text="ROI 道号（含两端）").pack(side="left")
        for variable in (self.roi_first, self.roi_last):
            ttk.Entry(roi, textvariable=variable, width=7).pack(side="left", padx=3)
        ttk.Button(roi, text="计算峰心", command=lambda: self.act(self.apply_roi)).pack(side="left", padx=4)
        self.energy_axis = tk.BooleanVar(value=True)
        ttk.Checkbutton(roi, text="MeV 横轴（需刻度）", variable=self.energy_axis,
                        command=self.draw).pack(side="left", padx=4)
        calibration = ttk.LabelFrame(self.spectrum_tools, text="两点能量刻度 · MeV", padding=6)
        calibration.pack(fill="x")
        self.calibration_vars = [tk.StringVar() for _ in range(4)]
        for i, (label, variable) in enumerate(zip(("道 1", "MeV 1", "道 2", "MeV 2"), self.calibration_vars)):
            ttk.Label(calibration, text=label).grid(row=0, column=i * 2)
            ttk.Entry(calibration, textvariable=variable, width=8).grid(row=0, column=i * 2 + 1, padx=3)
        for i, (text, action) in enumerate((("应用刻度", self.apply_calibration),
                                          ("保存刻度…", self.save_calibration),
                                          ("载入刻度…", self.load_calibration))):
            ttk.Button(calibration, text=text, command=lambda a=action: self.act(a)).grid(row=1, column=i * 2, columnspan=2, pady=(5, 0), sticky="ew")
        self.counter_tools = ttk.Frame(right)
        ttk.Label(self.counter_tools, text="扣本底：按当前设备实例，使用所选段曝光归一化").pack(anchor="w", pady=5)
        self.background_box = ttk.Combobox(self.counter_tools, state="readonly")
        self.background_box.pack(fill="x")
        self.background_box.bind("<<ComboboxSelected>>", self.change_background)
        self.message = tk.StringVar(value="读数仅包含已完成的曝光窗；停止采集可结清不足一秒的曝光。")
        ttk.Label(outer, textvariable=self.message, wraplength=1100).pack(anchor="w", pady=(8, 0))
        self.rebuild()
        self.schedule()

    def act(self, action):
        from tkinter import messagebox
        try:
            action()
            self.refresh()
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.message.set(str(error))
            self.dialog(messagebox.showerror, "Nuclemu · 操作未完成", str(error), parent=self.root)

    def dialog(self, action, *args, **kwargs):
        """Modal UI freezes physical time, including Tk's nested event loop."""
        self.sync_time()
        self.dialog_depth += 1
        try:
            return action(*args, **kwargs)
        finally:
            self.last_tick = self.clock()
            self.dialog_depth -= 1

    def rebuild(self):
        c = self.controller
        self.experiment_box.current(self.experiment_ids.index(c.current))
        self.description.configure(text=c.session.experiment.description)
        for child in self.parameters.winfo_children():
            child.destroy()
        self.parameter_vars = {}
        for row, parameter in enumerate(c.session.experiment.parameters):
            self.ttk.Label(self.parameters, text=f"{parameter.label} ({parameter.unit})" if parameter.unit else parameter.label).grid(row=row, column=0, sticky="w")
            variable = self.tk.StringVar(value=str(c.session.settings[parameter.key]))
            self.parameter_vars[parameter.key] = variable
            self.ttk.Entry(self.parameters, textvariable=variable, width=10).grid(row=row, column=1, padx=6, pady=3)
        self.ttk.Button(self.parameters, text="应用参数", command=lambda: self.act(self.apply_parameters)).grid(row=len(self.parameter_vars), column=0, columnspan=2, sticky="ew", pady=(5, 0))
        self.device_ids = [d.id for d in c.session.experiment.devices]
        self.device_box.configure(values=[f"{d.label} [{d.kind} · {d.id}]" for d in c.session.experiment.devices])
        self.device_box.current(self.device_ids.index(c.device.id))
        self.setup_device()
        self.render_key = None
        self.refresh()

    def setup_device(self):
        self.spectrum_tools.pack_forget()
        self.counter_tools.pack_forget()
        self.canvas.pack_forget()
        self.counter_table_frame.pack_forget()
        c = self.controller
        if c.device.kind == "spectrum":
            self.roi = self.rois.get((c.current, c.device.id), (0, c.device.channels - 1))
            self.roi_first.set(str(self.roi[0]))
            self.roi_last.set(str(self.roi[1]))
            self.spectrum_tools.pack(fill="x")
            self.canvas.pack(fill="both", expand=True)
        elif c.device.kind == "counter":
            self.counter_tools.pack(fill="x")
            self.counter_table_frame.pack(fill="both", expand=True)
        else:
            self.canvas.pack(fill="both", expand=True)
        self.show_calibration(c.active_calibration())

    def show_calibration(self, calibration):
        self.shown_calibration = calibration
        values = (calibration.channel1, calibration.energy1, calibration.channel2, calibration.energy2) if calibration else ("", "", "", "")
        for variable, value in zip(self.calibration_vars, values):
            variable.set(str(value))

    def change_experiment(self, event=None):
        c = self.controller
        target = self.experiment_ids[self.experiment_box.current()]
        if target == c.current:
            return
        self.sync_time()
        c.stop()
        c.switch(target)
        self.message.set("已保留前一实验的读数；切回即可继续查看或导出。")
        self.last_tick = self.clock()
        self.rebuild()

    def change_device(self, event=None):
        self.controller.bind_device(self.device_ids[self.device_box.current()])
        self.setup_device()
        self.render_key = None
        self.refresh()

    def apply_parameters(self):
        self.sync_time()
        self.controller.configure({key: variable.get() for key, variable in self.parameter_vars.items()})
        self.render_key = None

    def start(self):
        self.sync_time()
        self.apply_parameters()
        self.controller.start(self.duration.get() if self.mode.get() == "定时" else None)
        self.controller.select(None)
        self.render_key = None

    def stop(self):
        self.sync_time()
        self.controller.stop()

    def change_clock(self):
        self.sync_time()
        self.controller.set_speed(self.speed.get())

    def change_pause(self):
        self.sync_time()
        self.controller.paused = self.pause.get()

    def select_history(self, event=None):
        if self.history.curselection():
            self.controller.select(self.history.curselection()[0])
            self.render_key = None
            self.act(self.update_reading)

    def follow_latest(self):
        self.controller.select(None)
        self.render_key = None

    def select_counter_row(self, event=None):
        selection = self.counter_table.selection()
        if selection:
            index = int(selection[0])
            c = self.controller
            current = len(c.product()["segments"]) - 1 if c.lab.selected is None else c.lab.selected
            if index != current:
                c.select(index)
                self.render_key = None
                self.act(self.update_reading)

    def change_background(self, event=None):
        index = self.background_box.current() - 1
        self.controller.set_background(None if index < 0 else index)
        self.act(self.update_reading)

    def export(self, all_segments=False):
        from tkinter import filedialog
        path = self.dialog(filedialog.asksaveasfilename, parent=self.root, title="导出测量读数", defaultextension=".json",
                    filetypes=(("测量 JSON", "*.json"), ("数据 CSV", "*.csv")))
        if path:
            self.controller.export(path, all_segments=all_segments)
            self.message.set(f"已导出 {path}")

    def apply_calibration(self):
        self.shown_calibration = self.controller.calibrate(*(v.get() for v in self.calibration_vars))
        self.update_reading()
        self.draw()

    def save_calibration(self):
        from tkinter import filedialog
        if self.controller.active_calibration() is None:
            raise ValueError("请先为当前工况应用两点刻度。")
        path = self.dialog(filedialog.asksaveasfilename, parent=self.root, title="保存能量刻度", defaultextension=".json", filetypes=(("刻度 JSON", "*.json"),))
        if path:
            self.controller.save_calibration(path)
            self.message.set(f"已保存刻度 {path}")

    def load_calibration(self):
        from tkinter import filedialog
        path = self.dialog(filedialog.askopenfilename, parent=self.root, title="载入能量刻度", filetypes=(("刻度 JSON", "*.json"),))
        if path:
            self.controller.load_calibration(path)
            self.setup_device()
            self.update_reading()
            self.draw()

    def sync_time(self):
        now = self.clock()
        elapsed = now - self.last_tick
        self.last_tick = now
        if not self.dialog_depth:
            self.controller.advance(elapsed)

    def schedule(self):
        self.after_id = self.root.after(100, self.tick)

    def tick(self):
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
        self.after_id = None
        try:
            self.sync_time()
            self.refresh()
        except (ValueError, OSError) as error:
            self.controller.paused = True
            self.pause.set(True)
            self.message.set(f"仿真已暂停：{error}")
        self.schedule()

    def refresh(self):
        c = self.controller
        self.status.set(f"仿真时间 {c.session.time_s:.2f} s · {'已暂停' if c.paused else '运行'} · {'采集中' if c.session.running else '采集门关闭'} · seed={c.seed}")
        self.start_button.configure(state="disabled" if c.session.running else "normal")
        self.stop_button.configure(state="normal" if c.session.running else "disabled")
        key = (c.current, len(c.session.records), c.device.id, c.lab.selected)
        if key == self.render_key:
            return
        calibration = c.active_calibration()
        if calibration != self.shown_calibration:
            self.show_calibration(calibration)
        segments = c.product()["segments"]
        labels = [f"{i + 1}. {s['start_s']:g}–{s['end_s']:g} s · {s['settings']}" for i, s in enumerate(segments)]
        self.history.delete(0, "end")
        for label in labels:
            self.history.insert("end", label)
        if segments:
            selected = len(segments) - 1 if c.lab.selected is None else c.lab.selected
            self.history.selection_set(selected)
            self.history.see(selected)
        if c.device.kind == "counter":
            self.counter_table.delete(*self.counter_table.get_children())
            for i, segment in enumerate(segments):
                count = sum(segment["readings"][c.device.id])
                exposure = segment["end_s"] - segment["start_s"]
                self.counter_table.insert("", "end", iid=str(i), values=(
                    i + 1, str(segment["settings"]), count, f"{exposure:g}", f"{count / exposure:.6g}"))
            if segments:
                self.counter_table.selection_set(str(selected))
                self.counter_table.see(str(selected))
        self.background_box.configure(values=["不扣本底", *labels])
        self.background_box.current(0 if c.lab.background is None else c.lab.background + 1)
        self.update_reading()
        self.draw()
        self.render_key = key

    def update_reading(self):
        c = self.controller
        first, last = self.roi if c.device.kind == "spectrum" else (0, None)
        reading = c.readout(first, last)
        if reading is None:
            self.reading.set("等待采集 · 读数仅包含已完成的曝光窗")
            return
        text = f"计数 {reading['counts']} · 曝光 {reading['exposure_s']:g} s · 计数率 {reading['rate']:.4g} s⁻¹"
        if "centroid" in reading:
            center = reading["centroid"]
            text += "\nROI 峰心 " + ("无计数" if center is None else f"{center:.3f} 道")
            if reading["energy_MeV"] is not None:
                text += f" · {reading['energy_MeV']:.5g} MeV"
            elif c.device.id in c.lab.calibrations and c.active_calibration() is None:
                text += " · 当前工况使用道号（刻度不匹配）"
        if "net_rate" in reading:
            text += f"\n净计数率 {reading['net_rate']:.4g} ± {reading['uncertainty']:.3g} s⁻¹（标准不确定度）"
        if reading.get("background_reference"):
            text += "\n此段为所选本底；选择另一段以计算净率。"
        self.reading.set(text)

    def apply_roi(self):
        first, last = int(self.roi_first.get()), int(self.roi_last.get())
        c = self.controller
        if not 0 <= first <= last < c.device.channels:
            raise ValueError("ROI 道号应递增并位于当前谱仪范围内。")
        self.roi = first, last
        self.rois[c.current, c.device.id] = self.roi
        self.update_reading()

    def draw(self):
        canvas, c = self.canvas, self.controller
        if c.device.kind == "counter":
            return
        canvas.delete("all")
        w, h = max(canvas.winfo_width(), 300), max(canvas.winfo_height(), 180)
        left, top, right, bottom = 55, 25, w - 18, h - 42
        canvas.create_line(left, top, left, bottom, right, bottom, fill="#8997aa")
        segment = c.segment()
        if segment is None:
            canvas.create_text(w / 2, h / 2, text="开始采集以记录实验读数", fill="#b7cadf")
            return
        counts = segment["readings"][c.device.id]
        peak = max(max(counts), 1)
        canvas.create_text(left - 8, top, text=str(peak), fill="#b7cadf", anchor="e")
        canvas.create_text(left - 8, bottom, text="0", fill="#b7cadf", anchor="e")
        canvas.create_text(left, 10, text="计数", fill="#b7cadf", anchor="w")
        if c.device.kind == "spectrum":
            points = []
            for i, value in enumerate(counts):
                points.extend((left + i / max(1, len(counts) - 1) * (right - left),
                               bottom - value / peak * (bottom - top)))
            if len(points) >= 4:
                canvas.create_line(*points, fill="#6ee7dc", width=1.5)
            calibration = c.active_calibration() if self.energy_axis.get() else None
            for fraction in (0, .25, .5, .75, 1):
                channel = fraction * (len(counts) - 1)
                label = f"{calibration.energy(channel):.3g}" if calibration else f"{channel:.0f}"
                canvas.create_text(left + fraction * (right - left), bottom + 12, text=label, fill="#b7cadf")
            canvas.create_text((left + right) / 2, h - 7, text="能量 / MeV" if calibration else "道号", fill="#b7cadf")
        else:
            canvas.create_rectangle(left + 40, bottom - counts[0] / peak * (bottom - top), right - 40, bottom, fill="#6ee7dc", outline="")
            canvas.create_text((left + right) / 2, bottom + 18, text=c.device.label, fill="#b7cadf")

    def close(self):
        from tkinter import messagebox
        self.sync_time()
        unsaved = []
        for key, lab in self.controller.labs.items():
            reasons = []
            saved = lab.saved
            if lab.session.running:
                reasons.append("采集中")
            if any(saved.get((i, d.id)) != s["end_s"]
                   for i, s in enumerate(lab.view.product()["segments"])
                   for d in lab.session.experiment.devices):
                reasons.append("未导出读数")
            if any(lab.saved_calibrations.get(device) != calibration
                   for device, calibration in lab.calibrations.items()):
                reasons.append("未保存刻度")
            if reasons:
                unsaved.append(f"{self.controller.definitions[key].title}：{'、'.join(reasons)}")
        if unsaved and not self.dialog(messagebox.askokcancel, "关闭实验台", "\n".join(unsaved) +
                "\n关闭会停止采集并丢弃未保存内容。继续关闭？\n确认期间仿真时间冻结，取消后继续。", parent=self.root):
            self.refresh()
            return
        self.controller.stop()
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.root.destroy()


def launch(paths=()):
    """Start the local browser workbench with the same discovery paths as the CLI."""
    from .web import launch as launch_web

    launch_web(paths=paths)
