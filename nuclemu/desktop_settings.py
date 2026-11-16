"""A small, non-modal editor for the next desktop startup attempt."""

from .desktop_dpi import window_dpi, work_area


class SettingsWindow:
    def __init__(self, launcher):
        import tkinter as tk
        from tkinter import font
        from pathlib import Path
        import sys
        from .desktop import INK, MUTED, EDGE, ACCENT, FOCUS

        self.launcher = launcher
        self.root = tk.Toplevel(launcher.root, background='white')
        self.root.title('Nuclemu 设置')
        if sys.platform == 'win32':
            self.root.iconbitmap(str(Path(__file__).with_name('static') / 'nuclemu.ico'))
        elif hasattr(launcher, '_icon_image'):
            self.root.iconphoto(False, launcher._icon_image)
        self.root.transient(launcher.root)
        self.root.resizable(False, False)
        self.root.protocol('WM_DELETE_WINDOW', self.cancel)
        self.root.bind('<Escape>', lambda event: self.cancel())
        self.root.bind('<Destroy>', self._destroyed, add='+')
        self.dpi = None
        self.fonts = {name: font.Font(self.root, family=launcher.fonts['body'].actual('family'),
                                    weight='bold' if name == 'brand' else 'normal')
                      for name in ('body', 'brand')}
        self.body = tk.Frame(self.root, background='white')
        self.body.pack(fill='both', expand=True)
        self.body.columnconfigure(0, weight=1)
        self.heading = tk.Label(self.body, text='设置', font=self.fonts['brand'],
                                foreground=INK, background='white', anchor='w')
        self.heading.grid(row=0, sticky='ew')
        self.port_label = tk.Label(self.body, text='工作台端口', font=self.fonts['body'],
                                  foreground=INK, background='white', anchor='w')
        self.port_label.grid(row=1, sticky='ew')
        self.port_row = tk.Frame(self.body, background='white')
        self.port_row.grid(row=2, sticky='w')
        self.automatic = tk.BooleanVar(value=launcher.settings.port == 0)
        self.port = tk.StringVar(value=str(launcher.settings.port or 8080))
        self.segment = tk.Frame(self.port_row, background=EDGE)
        self.segment.grid(row=0, column=0, sticky='ns')
        self.radios = []
        for column, (label, value) in enumerate((('自动', True), ('固定', False))):
            radio = tk.Radiobutton(self.segment, text=label, variable=self.automatic,
                value=value, indicatoron=False, font=self.fonts['body'],
                borderwidth=0, highlightthickness=0, relief='flat', offrelief='flat',
                selectcolor=ACCENT, background='white', activebackground='#f7f9fa',
                takefocus=True, cursor='hand2')
            radio.grid(row=0, column=column, sticky='w')
            radio.bind('<FocusIn>', lambda event: self.segment.configure(background=FOCUS))
            radio.bind('<FocusOut>', lambda event: self.segment.configure(background=EDGE))
            radio.bind('<Left>', lambda event: self._select_port(True))
            radio.bind('<Right>', lambda event: self._select_port(False))
            radio.bind('<Return>', lambda event, control=radio: (control.invoke(), 'break')[1])
            self.radios.append(radio)
        self.entry_shell = tk.Frame(self.port_row, background=EDGE)
        self.entry_shell.grid(row=0, column=1, sticky='ns')
        self.entry_inner = tk.Frame(self.entry_shell, background='white')
        self.entry_inner.pack(fill='both', expand=True)
        self.port_entry = tk.Entry(self.entry_inner, textvariable=self.port, width=7,
            font=self.fonts['body'], foreground=INK, background='white', relief='flat',
            borderwidth=0, highlightthickness=0, selectbackground=ACCENT,
            selectforeground='white', disabledbackground='#f7f9fa')
        self.port_entry.pack(fill='both', expand=True)
        self.port_entry.bind('<FocusIn>', lambda event: self.entry_shell.configure(background=FOCUS))
        self.port_entry.bind('<FocusOut>', lambda event: self.entry_shell.configure(background=EDGE))
        self.help = tk.Label(self.body,
            font=self.fonts['body'], foreground=MUTED, background='white', anchor='w', justify='left')
        self.help.grid(row=3, sticky='ew')
        self.open_browser = tk.BooleanVar(value=launcher.settings.open_browser)
        self.browser_row = tk.Frame(self.body, background='white')
        self.browser_row.grid(row=4, sticky='ew')
        self.browser_row.columnconfigure(0, weight=1)
        tk.Label(self.browser_row, text='启动时在浏览器中打开工作台', font=self.fonts['body'],
                 foreground=INK, background='white').grid(row=0, column=0, sticky='w')
        self.switch_shell = tk.Frame(self.browser_row, background='white')
        self.switch_shell.grid(row=0, column=1, sticky='e')
        self.open_check = tk.Checkbutton(self.switch_shell, variable=self.open_browser,
            font=self.fonts['body'], foreground=INK, background='white',
            activebackground='white', activeforeground=INK, indicatoron=False,
            selectcolor='white', relief='flat', offrelief='flat', borderwidth=0,
            highlightthickness=0, takefocus=True, cursor='hand2', compound='right')
        self.open_check.pack()
        self.open_check.bind('<FocusIn>', lambda event: self.switch_shell.configure(background=FOCUS))
        self.open_check.bind('<FocusOut>', lambda event: self.switch_shell.configure(background='white'))
        self.open_check.bind('<Return>', lambda event: (self.open_check.invoke(), 'break')[1])
        self.automatic.trace_add('write', self._port_mode)
        self.open_browser.trace_add('write', self._browser_mode)
        self.explanation = tk.Label(self.body, text='下次启动或重试时生效。',
            font=self.fonts['body'], foreground=MUTED, background='white', justify='left', anchor='w')
        self.explanation.grid(row=5, sticky='ew')
        self.error = tk.StringVar(value=launcher.settings_error or '')
        self.error_label = tk.Label(self.body, textvariable=self.error, font=self.fonts['body'],
            foreground='#9b2c21', background='white', justify='left', anchor='w')
        self.error_label.grid(row=6, sticky='ew')
        self.actions = tk.Frame(self.body, background='white')
        self.actions.grid(row=7, sticky='e')
        self.cancel_button = launcher.button(self.actions, '取消', self.cancel)
        self.cancel_button.shell.grid(row=0, column=0)
        self.save_button = launcher.button(self.actions, '保存', self.save, primary=True)
        self.save_button.shell.grid(row=0, column=1)
        for button in (self.cancel_button, self.save_button):
            button.configure(font=self.fonts['body'])
        self._port_mode()
        self._apply_dpi()
        self.root.geometry(f'+{launcher.root.winfo_rootx() + (launcher.root.winfo_width() - self.root.winfo_width()) // 2}'
                           f'+{launcher.root.winfo_rooty() + launcher.px(24)}')
        self.root.bind('<Configure>', self._configured, add='+')
        from .desktop_chrome import blend_windows_caption
        self.root.update_idletasks()
        self.blended_caption = blend_windows_caption(self.root)

    def _select_port(self, automatic):
        self.automatic.set(automatic)
        self.radios[0 if automatic else 1].focus_set()
        return 'break'

    def _port_mode(self, *args):
        from .desktop import INK
        for radio, selected in zip(self.radios, (self.automatic.get(), not self.automatic.get())):
            radio.configure(foreground='white' if selected else INK,
                            activeforeground='white' if selected else INK,
                            activebackground='#204984' if selected else '#f7f9fa')
        self.port_entry.configure(state='disabled' if self.automatic.get() else 'normal')
        if self.automatic.get():
            self.entry_shell.grid_remove()
        else:
            self.entry_shell.grid()
        self.help.configure(text='由系统分配可用端口。' if self.automatic.get() else '端口范围：1–65535。')

    def _browser_mode(self, *args):
        enabled = self.open_browser.get()
        self.open_check.configure(text='开启' if enabled else '关闭', image=self.switch_images[enabled])

    def _switch_images(self, px):
        import tkinter as tk
        from math import sqrt
        images = {}
        width, height, radius = px(48), px(26), px(13)
        for enabled in (False, True):
            image = tk.PhotoImage(master=self.root, width=width, height=height)
            track = '#2956a1' if enabled else '#667580'
            for y in range(height):
                inset = max(0, round(radius - sqrt(max(0, radius ** 2 - (y + .5 - height / 2) ** 2))))
                image.put(track, to=(inset, y, width - inset, y + 1))
            knob, center = px(9), width - radius if enabled else radius
            for y in range(round(height / 2 - knob), round(height / 2 + knob)):
                span = round(sqrt(max(0, knob ** 2 - (y + .5 - height / 2) ** 2)))
                if span:
                    image.put('white', to=(center - span, y, center + span, y + 1))
            images[enabled] = image
        self.switch_images = images
        self._browser_mode()

    def _configured(self, event):
        if event.widget == self.root and abs(window_dpi(self.root) - self.dpi) > .5:
            self._apply_dpi()

    def _apply_dpi(self):
        self.dpi = window_dpi(self.root)
        px = lambda value: max(1, round(value * self.dpi / 96))
        for name, factor in (('body', 1), ('brand', 1.4)):
            self.fonts[name].configure(size=-px(self.launcher._body_size * factor))
        self.body.pack_configure(padx=px(24), pady=px(22))
        self.heading.grid_configure(pady=(0, px(20)))
        self.port_label.grid_configure(pady=(0, px(8)))
        self.help.grid_configure(pady=(px(6), px(20)))
        self.browser_row.grid_configure(pady=(0, px(12)))
        self.explanation.grid_configure(pady=(0, px(16)))
        self.error_label.configure(wraplength=px(440))
        self.error_label.grid_configure(pady=(0, px(16)))
        if not self.error.get():
            self.error_label.grid_remove()
        for column, radio in enumerate(self.radios):
            radio.configure(padx=px(16), pady=px(8))
            radio.grid_configure(padx=(px(1) if column == 0 else 0, px(1)), pady=px(1))
        self.entry_shell.grid_configure(padx=(px(12), 0))
        self.port_row.columnconfigure(1, minsize=self.fonts['body'].measure('0000000') + px(30))
        self.entry_inner.pack_configure(padx=px(1), pady=px(1))
        self.port_entry.pack_configure(padx=px(8), pady=px(6))
        self._switch_images(px)
        self.open_check.configure(padx=px(6), pady=px(4))
        self.open_check.pack_configure(padx=px(1), pady=px(1))
        self._port_mode()
        self.save_button.shell.grid_configure(padx=(px(12), 0))
        for button in (self.cancel_button, self.save_button):
            button.configure(padx=px(16), pady=px(8))
            button.pack_configure(padx=px(1), pady=px(1))
        self.root.update_idletasks()
        area_width, area_height = work_area(self.root)
        self.root.geometry(f'{min(max(px(480), self.root.winfo_reqwidth()), area_width)}x'
                           f'{min(self.root.winfo_reqheight(), area_height)}')

    def activate(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def save(self):
        from .launcher_settings import LauncherSettings
        if self.launcher.closing or self.launcher.checking_close:
            return
        try:
            text = self.port.get().strip()
            if not self.automatic.get() and (not text.isascii() or not text.isdecimal()
                                              or not 1 <= int(text) <= 65535):
                raise ValueError('固定端口须为 1–65535 的整数。')
            value = LauncherSettings(0 if self.automatic.get() else int(text), self.open_browser.get())
            self.launcher.save_settings(value)
        except (ValueError, OSError) as error:
            self.error.set(str(error))
            self.error_label.grid()
            self._apply_dpi()
            return
        self.cancel()

    def cancel(self):
        self.root.destroy()

    def _destroyed(self, event):
        if event.widget == self.root:
            self.launcher.settings_window = None
