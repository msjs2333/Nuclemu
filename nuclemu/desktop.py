"""Small desktop owner for the local workbench service."""

from queue import Empty, SimpleQueue
from threading import Thread
from pathlib import Path
import sys
import webbrowser

from .desktop_dpi import enable_windows_dpi_awareness, window_dpi, work_area

INK, MUTED, EDGE = '#101010', '#46525b', '#c8d1d6'
ACCENT, HOVER, PLANE, FOCUS = '#2956a1', '#204984', '#f7f9fa', '#376cc2'


class _Launcher:
    def __init__(self, root, service):
        import tkinter as tk
        from tkinter import font

        self.root, self.service = root, service
        self.closed = self.closing = self.checking_close = False
        self.messages = SimpleQueue()
        self.url = None
        self._jobs = set()
        self._fit_pending = self._fitting = False
        self._logical_width = 500
        self.dpi = window_dpi(root)
        self.scale = self.dpi / 96
        root.title('Nuclemu')
        root.configure(background='white')
        root.resizable(False, False)
        root.columnconfigure(0, weight=1)
        families = {name.casefold(): name for name in font.families(root)}
        preferred = (['Microsoft YaHei UI', 'Microsoft YaHei', 'Segoe UI'] if sys.platform == 'win32'
                     else ['PingFang SC', 'Helvetica Neue'] if sys.platform == 'darwin'
                     else ['Noto Sans CJK SC', 'Noto Sans SC', 'DejaVu Sans'])
        default = font.nametofont('TkDefaultFont', root)
        family = next((families[name.casefold()] for name in preferred if name.casefold() in families), default.actual('family'))
        size = default.cget('size')
        self._body_size = max(14, size * 96 / 72 if size > 0 else abs(size) / self.scale)
        self.fonts = {name: font.Font(root, family=family, weight=weight)
                      for name, weight in [('body', 'normal'), ('small', 'normal'), ('brand', 'bold')]}
        self.body = tk.Frame(root, background='white')
        self.body.grid(sticky='ew')
        self.body.columnconfigure(0, weight=1)
        self.header = tk.Frame(self.body, background='white')
        self.header.grid(row=0, sticky='ew')
        self.header.columnconfigure(0, weight=1)
        tk.Label(self.header, text='本机工作台', font=self.fonts['brand'], background='white', foreground=INK).grid(row=0, column=0, sticky='w')
        self.status = tk.StringVar(value='正在启动…')
        self.status_label = tk.Label(self.header, textvariable=self.status, font=self.fonts['body'], background='white', foreground=MUTED)
        self.status_label.grid(row=0, column=1, sticky='e')
        self.message = tk.StringVar(value='本机工作台就绪后，可在浏览器中进入实验。')
        self.message_box = tk.Frame(self.body, background='white')
        self.message_box.grid(row=1, sticky='ew')
        self.message_box.columnconfigure(0, weight=1)
        self.message_text = tk.Text(self.message_box, font=self.fonts['body'], foreground=MUTED,
            background='white', wrap='word', borderwidth=0, highlightthickness=0, height=2,
            cursor='arrow', state='disabled', selectbackground=ACCENT, selectforeground='white')
        self.message_text.grid(row=0, column=0, sticky='ew')
        self.message_scroll = tk.Scrollbar(self.message_box, command=self.message_text.yview)
        self.message_text.configure(yscrollcommand=self.message_scroll.set)
        self.ready = tk.Frame(self.body, background=PLANE)
        self.ready.columnconfigure(0, weight=1)
        self.address_label = tk.Label(self.ready, text='工作台地址', font=self.fonts['small'], foreground=MUTED, background=PLANE)
        self.address_label.grid(row=0, column=0, columnspan=2, sticky='w')
        self.address = tk.StringVar()
        self.address_shell = tk.Frame(self.ready, background=EDGE)
        self.address_shell.grid(row=1, column=0, sticky='nsew')
        self.address_inner = tk.Frame(self.address_shell, background='white')
        self.address_inner.pack(fill='both', expand=True)
        self.address_entry = tk.Entry(self.address_inner, textvariable=self.address, state='readonly',
            font=self.fonts['body'], foreground=INK, readonlybackground='white', relief='flat',
            borderwidth=0, highlightthickness=0,
            selectbackground=ACCENT, selectforeground='white')
        self.address_entry.pack(fill='both', expand=True)
        self.address_entry.bind('<FocusIn>', lambda event: self.address_shell.configure(background=FOCUS))
        self.address_entry.bind('<FocusOut>', lambda event: self.address_shell.configure(background=EDGE))
        self.copy_button = self.button(self.ready, '复制地址', self.copy_address)
        self.copy_button.shell.grid(row=1, column=1, sticky='ns')
        self.actions = tk.Frame(self.body, background='white')
        self.actions.grid(row=3, sticky='ew')
        self.actions.columnconfigure(0, weight=1)
        self.open_button = self.button(self.actions, '在浏览器中打开', self.open_browser, primary=True)
        self.open_button.shell.grid(row=0, column=0, sticky='w')
        self.open_button.shell.grid_remove()
        self.close_button = self.button(self.actions, '关闭', self.request_close)
        self.close_button.shell.grid(row=0, column=1, sticky='e')
        self.message.trace_add('write', self._message_changed)
        self._message_changed()
        self._apply_dpi(self.dpi)
        self._load_icon()
        root.bind('<Configure>', self._configured, add='+')
        root.bind('<Destroy>', self._destroyed, add='+')
        root.protocol('WM_DELETE_WINDOW', self.request_close)
        self._later(0, self.start)
        self._later(50, self.poll)
        self._later(250, self._check_dpi)

    def _later(self, delay, callback):
        def run():
            self._jobs.discard(job)
            callback()
        job = self.root.after_idle(run) if delay is None else self.root.after(delay, run)
        self._jobs.add(job)

    def _destroyed(self, event):
        if event.widget == self.root:
            self.closed = True
            for job in self._jobs:
                self.root.after_cancel(job)
            self._jobs.clear()

    def px(self, value):
        return max(1, round(value * self.scale))

    def button(self, parent, text, command, primary=False):
        import tkinter as tk
        background = ACCENT if primary else 'white'
        shell = tk.Frame(parent, background=ACCENT if primary else EDGE)
        button = tk.Button(shell, text=text, command=command, font=self.fonts['body'],
            background=background, foreground='white' if primary else INK,
            activebackground=HOVER if primary else PLANE, activeforeground='white' if primary else INK,
            relief='flat', borderwidth=0, highlightthickness=0, cursor='hand2', takefocus=True)
        button.shell = shell
        button.pack(fill='both', expand=True)
        button.primary = primary
        button.bind('<FocusIn>', lambda event: shell.configure(background=FOCUS))
        button.bind('<FocusOut>', lambda event: shell.configure(background=ACCENT if primary else EDGE))
        button.bind('<Return>', lambda event: (button.invoke(), 'break')[1])
        button.bind('<Enter>', lambda event: button.configure(background=HOVER if primary else PLANE)
                    if str(button['state']) != 'disabled' else None)
        button.bind('<Leave>', lambda event: button.configure(background=background)
                    if str(button['state']) != 'disabled' else None)
        return button

    def _enable(self, button, enabled):
        button.configure(state='normal' if enabled else 'disabled',
            background=ACCENT if enabled and button.primary else 'white' if enabled else PLANE,
            disabledforeground=MUTED)

    def _load_icon(self):
        import tkinter as tk
        folder = Path(__file__).with_name('static')
        if sys.platform == 'win32' and (folder / 'nuclemu.ico').is_file():
            self.root.iconbitmap(str(folder / 'nuclemu.ico'))
        elif (folder / 'nuclemu-mark.png').is_file():
            self._icon_image = tk.PhotoImage(master=self.root, file=str(folder / 'nuclemu-mark.png'))
            self.root.iconphoto(True, self._icon_image)

    def _apply_dpi(self, dpi):
        self.dpi, self.scale = dpi, dpi / 96
        # Negative Tk font sizes are pixels. Apply the window DPI exactly once;
        # do not also multiply tk scaling or the native theme's dimensions.
        for name, size in [('body', self._body_size), ('small', self._body_size - 1), ('brand', self._body_size * 1.4)]:
            self.fonts[name].configure(size=-self.px(size))
        address_width = self.fonts['body'].measure('http://127.0.0.1:65535/')
        copy_width = self.fonts['body'].measure('复制地址')
        self._logical_width = max(500, (address_width + copy_width) / self.scale + 114)
        self.body.grid_configure(padx=self.px(24), pady=self.px(22))
        self.header.grid_configure(pady=(0, self.px(16)))
        self.message_box.grid_configure(pady=(0, self.px(16)))
        if not self.message.get():
            self.message_box.grid_remove()
        self.ready.configure(padx=self.px(12), pady=self.px(10))
        self.address_label.grid_configure(pady=(0, self.px(6)))
        self.address_inner.pack_configure(padx=self.px(1), pady=self.px(1))
        self.address_entry.pack_configure(padx=self.px(8), pady=self.px(8))
        self.copy_button.shell.grid_configure(padx=(self.px(8), 0))
        self.actions.grid_configure(pady=(self.px(16), 0))
        self.close_button.shell.grid_configure(padx=(self.px(12), 0))
        for button in (self.copy_button, self.open_button, self.close_button):
            button.configure(padx=self.px(16), pady=self.px(8))
            button.pack_configure(padx=self.px(1), pady=self.px(1))
        self.root.minsize(1, 1)
        self.root.geometry(f'{round(self._logical_width * self.scale)}x{self.root.winfo_height()}')
        self._schedule_fit()

    def _configured(self, event):
        if event.widget != self.root or self._fitting:
            return
        dpi = window_dpi(self.root)
        if abs(dpi - self.dpi) > .5:
            self._apply_dpi(dpi)

    def _check_dpi(self):
        if self.closed:
            return
        dpi = window_dpi(self.root)
        if abs(dpi - self.dpi) > .5:
            self._apply_dpi(dpi)
        self._later(250, self._check_dpi)

    def _message_changed(self, *args):
        if self.message.get():
            self.message_box.grid()
        else:
            self.message_box.grid_remove()
        self.message_text.configure(state='normal')
        self.message_text.delete('1.0', 'end')
        self.message_text.insert('1.0', self.message.get())
        self.message_text.configure(state='disabled')
        self.message_text.yview_moveto(0)
        self._schedule_fit()

    def _schedule_fit(self):
        if not self._fit_pending and not self.closed:
            self._fit_pending = True
            self._later(None, self._fit)

    def _fit(self):
        self._fit_pending = False
        if self.closed or self._fitting:
            return
        self._fitting = True
        try:
            area_width, area_height = work_area(self.root)
            minimum = min(self.px(460), area_width - self.px(32))
            width = min(max(minimum, round(self._logical_width * self.scale)), area_width - self.px(32))
            self.root.geometry(f'{width}x{self.root.winfo_height()}')
            self.root.update_idletasks()
            lines = (self.message_text.count('1.0', 'end-1c', 'displaylines') or (0,))[0] + 1
            maximum = max(2, min(8, int(area_height * .4 / self.fonts['body'].metrics('linespace'))))
            self.message_text.configure(height=min(lines, maximum))
            if lines > maximum:
                self.message_scroll.grid(row=0, column=1, sticky='ns', padx=(self.px(8), 0))
            else:
                self.message_scroll.grid_remove()
            self.root.update_idletasks()
            height = min(self.root.winfo_reqheight(), area_height - self.px(64))
            self.root.minsize(minimum, height)
            self.root.maxsize(area_width, area_height)
            self.root.geometry(f'{width}x{height}')
        finally:
            self._fitting = False

    def start(self):
        if not self.checking_close and self.service.status().phase == 'new':
            self.service.start()

    def open_browser(self):
        if not self.url or self.closing:
            return
        try:
            if not webbrowser.open(self.url):
                raise OSError('系统未能打开默认浏览器。')
        except Exception as error:
            self._notice(f'无法打开浏览器：{error} 可复制地址后在浏览器中打开。', error=True)

    def _notice(self, text, *, error=False):
        self.message_text.configure(foreground='#9b2c21' if error else MUTED)
        self.message.set(text)

    def copy_address(self):
        if self.url and not self.closing:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.url)
            self._notice('地址已复制，可粘贴到浏览器中打开。')

    def request_close(self):
        if self.closing or self.checking_close:
            return
        self.checking_close = True
        self._enable(self.close_button, False)
        def check():
            try:
                self.messages.put(('close', self.service.stop_if_idle()))
            except Exception as error:
                self.messages.put(('error', str(error)))
        Thread(target=check, name='nuclemu-desktop-close', daemon=True).start()

    def poll(self):
        while True:
            try:
                kind, result = self.messages.get_nowait()
            except Empty:
                break
            self.checking_close = False
            if kind == 'close' and result:
                self.closing = True
                self.status.set('正在关闭…')
                self._enable(self.open_button, False)
                self._enable(self.copy_button, False)
            else:
                self._enable(self.close_button, True)
                self._notice('实验仍在工作台中。请返回工作台退出实验，再关闭启动器。'
                             if kind == 'close' else f'无法关闭服务：{result}', error=kind == 'error')
        state = self.service.status()
        if self.closing:
            if state.phase in ('stopped', 'failed') and self.service.join(0):
                self.closed = True
                self.root.destroy()
                return
        elif state.phase == 'ready' and not self.url:
            self.url = state.url
            self.address.set(state.url)
            self.status.set('已就绪')
            self.status_label.configure(foreground=ACCENT)
            self._notice('')
            self.ready.grid(row=2, sticky='ew')
            self.open_button.shell.grid()
            self._schedule_fit()
        elif state.phase == 'failed' and self.status.get() != '启动失败':
            self.status.set('启动失败')
            self.status_label.configure(foreground='#9b2c21')
            self._notice(f'{state.error} 请关闭窗口后重试，或使用 nuclemu serve --no-gui。', error=True)
        self._later(50, self.poll)


def launch(paths=(), *, port=0, directory=None):
    """Show the launcher before discovering courses and starting its service."""
    enable_windows_dpi_awareness()
    try:
        import tkinter as tk
        root = tk.Tk()
    except ImportError as error:
        raise ImportError('无法加载桌面窗口，请使用 nuclemu serve --no-gui。') from error
    except tk.TclError as error:
        raise OSError(f'无法创建桌面窗口：{error}；请使用 nuclemu serve --no-gui。') from error
    try:
        from .web_service import WorkbenchService
        window = _Launcher(root, WorkbenchService(paths, port=port, directory=directory))
        root.update_idletasks()
    except Exception:
        root.destroy()
        raise
    while not window.closed:
        try:
            root.mainloop()
        except KeyboardInterrupt:
            window.request_close()
