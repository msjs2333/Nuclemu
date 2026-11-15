"""Choose an existing workbench or a separate service without a nested loop."""

from .desktop_dpi import window_dpi, work_area


class StartupWindow:
    def __init__(self, launcher, existing):
        import tkinter as tk
        from tkinter import font, ttk
        from pathlib import Path
        import sys
        from .desktop import INK, MUTED
        from .desktop_chrome import blend_windows_caption

        self.launcher, self.existing = launcher, existing
        self.root = tk.Toplevel(launcher.root, background='white')
        self.root.title('Nuclemu 已有工作台')
        self.root.transient(launcher.root)
        self.root.resizable(False, False)
        self.root.protocol('WM_DELETE_WINDOW', launcher.request_close)
        self.root.bind('<Escape>', lambda event: (launcher.request_close(), 'break')[1])
        self.root.bind('<Destroy>', self._destroyed, add='+')
        if sys.platform == 'win32':
            self.root.iconbitmap(str(Path(__file__).with_name('static') / 'nuclemu.ico'))
        elif hasattr(launcher, '_icon_image'):
            self.root.iconphoto(False, launcher._icon_image)
        self.dpi = None
        self.fonts = {name: font.Font(self.root, family=launcher.fonts['body'].actual('family'),
            weight='bold' if name == 'brand' else 'normal') for name in ('body', 'brand')}
        self.body = tk.Frame(self.root, background='white')
        self.body.pack(fill='both', expand=True)
        self.body.columnconfigure(0, weight=1)
        self.heading = tk.Label(self.body, text='已有 Nuclemu 工作台', font=self.fonts['brand'],
                                foreground=INK, background='white', anchor='w')
        self.heading.grid(row=0, sticky='ew')
        self.description = tk.Label(self.body, text='原工作台中的实验继续运行。\n并列启动将使用本次课程配置。',
            font=self.fonts['body'], foreground=MUTED, background='white', anchor='w', justify='left')
        self.description.grid(row=1, columnspan=2, sticky='ew')
        self.selection = ttk.Combobox(self.body, state='readonly', font=self.fonts['body'],
            values=[entry.url or '正在启动的工作台' for entry in existing])
        self.selection.grid(row=2, column=0, sticky='ew')
        self.selection.current(0)
        self.selection.bind('<<ComboboxSelected>>', self._selected)
        self.copy_button = launcher.button(self.body, '复制地址', self.copy)
        self.copy_button.shell.grid(row=2, column=1, sticky='e')
        self.course = tk.StringVar()
        self.course_label = tk.Label(self.body, textvariable=self.course, font=self.fonts['body'],
            foreground=MUTED, background='white', anchor='w', justify='left')
        self.course_label.grid(row=3, columnspan=2, sticky='ew')
        self.message = tk.StringVar()
        self.message_label = tk.Label(self.body, textvariable=self.message, font=self.fonts['body'],
            foreground='#9b2c21', background='white', anchor='w', justify='left')
        self.message_label.grid(row=4, columnspan=2, sticky='ew')
        self.actions = tk.Frame(self.body, background='white')
        self.actions.grid(row=5, columnspan=2, sticky='e')
        self.reuse_button = launcher.button(self.actions, '打开已有工作台', self.reuse, primary=True)
        self.new_button = launcher.button(self.actions, '启动并列服务', launcher.choose_start)
        self.reuse_button.shell.grid(row=0, column=0)
        self.new_button.shell.grid(row=0, column=1)
        self.buttons = (self.copy_button, self.reuse_button, self.new_button)
        for button in self.buttons:
            button.configure(font=self.fonts['body'])
        self._selected()
        self._apply_dpi()
        self.root.geometry(f'+{launcher.root.winfo_rootx() + (launcher.root.winfo_width() - self.root.winfo_width()) // 2}'
                           f'+{launcher.root.winfo_rooty() + launcher.px(24)}')
        self.root.update_idletasks()
        self.blended_caption = blend_windows_caption(self.root)
        self.root.bind('<Configure>', self._configured, add='+')

    def _selected(self, event=None):
        entry = self.existing[self.selection.current()]
        self.course.set('课程目录：' + ('、'.join(entry.paths) if entry.paths else '内置课程'))

    def _configured(self, event):
        if event.widget == self.root and abs(window_dpi(self.root) - self.dpi) > .5:
            self._apply_dpi()

    def _apply_dpi(self):
        self.dpi = window_dpi(self.root)
        px = lambda value: max(1, round(value * self.dpi / 96))
        for name, factor in (('body', 1), ('brand', 1.4)):
            self.fonts[name].configure(size=-px(self.launcher._body_size * factor))
        self.body.pack_configure(padx=px(24), pady=px(22))
        self.heading.grid_configure(pady=(0, px(14)))
        self.description.grid_configure(pady=(0, px(18)))
        self.description.configure(wraplength=px(452))
        self.copy_button.shell.grid_configure(padx=(px(12), 0))
        self.course_label.configure(wraplength=px(452))
        self.course_label.grid_configure(pady=(px(8), px(20)))
        self.message_label.configure(wraplength=px(452))
        self.message_label.grid_configure(pady=(0, px(16)))
        if not self.message.get():
            self.message_label.grid_remove()
        self.new_button.shell.grid_configure(padx=(px(12), 0))
        for button in self.buttons:
            button.configure(padx=px(16), pady=px(8))
            button.pack_configure(padx=px(1), pady=px(1))
        self.root.update_idletasks()
        width, height = work_area(self.root)
        self.root.geometry(f'{min(max(px(500), self.root.winfo_reqwidth()), width)}x'
                           f'{min(self.root.winfo_reqheight(), height)}')

    def activate(self):
        self.root.deiconify()
        self.root.lift()
        self.reuse_button.focus_set()

    def set_busy(self, busy):
        for button in self.buttons:
            self.launcher._enable(button, not busy)
        self.selection.configure(state='disabled' if busy else 'readonly')

    def notice(self, message):
        self.message.set(message)
        self.message_label.grid()
        self._apply_dpi()

    def copy(self):
        url = self.existing[self.selection.current()].url
        if url:
            self.root.clipboard_clear()
            self.root.clipboard_append(url)

    def reuse(self):
        self.launcher.choose_start(self.existing[self.selection.current()])

    def destroy(self):
        self.root.destroy()

    def _destroyed(self, event):
        if event.widget == self.root:
            self.launcher.startup_window = None
