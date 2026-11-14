"""Small desktop owner for the local workbench service."""

from queue import Empty, SimpleQueue
from threading import Thread
import webbrowser


class _Launcher:
    def __init__(self, root, service):
        import tkinter as tk
        from tkinter import font, ttk

        self.root, self.service = root, service
        self.closed = self.closing = self.checking_close = False
        self.messages = SimpleQueue()
        self.url = None
        root.title('Nuclemu')
        root.geometry('540x285')
        root.minsize(460, 265)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        body = ttk.Frame(root, padding=24)
        body.grid(sticky='nsew')
        body.columnconfigure(0, weight=1)
        self.heading_font = font.nametofont('TkDefaultFont').copy()
        self.heading_font.configure(size=16, weight='bold')
        self.status = tk.StringVar(value='正在启动…')
        ttk.Label(body, textvariable=self.status, font=self.heading_font).grid(sticky='w')
        self.message = tk.StringVar(value='本机工作台就绪后，可在浏览器中进入实验。')
        self.message_label = ttk.Label(body, textvariable=self.message, wraplength=490)
        self.message_label.grid(sticky='ew', pady=(10, 18))
        body.bind('<Configure>', lambda e: self.message_label.configure(wraplength=max(200, e.width - 48)))
        self.ready = ttk.Frame(body)
        self.ready.columnconfigure(0, weight=1)
        self.address = tk.StringVar()
        self.address_entry = ttk.Entry(self.ready, textvariable=self.address, state='readonly')
        self.address_entry.grid(row=0, column=0, sticky='ew')
        self.copy_button = ttk.Button(self.ready, text='复制地址', command=self.copy_address)
        self.copy_button.grid(row=0, column=1, padx=(8, 0))
        self.open_button = tk.Button(self.ready, text='在浏览器中打开', command=self.open_browser,
            background='#2956a1', foreground='white', activebackground='#204986',
            activeforeground='white', relief='flat', padx=16, pady=8, cursor='hand2')
        self.open_button.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(12, 0))
        body.rowconfigure(3, weight=1)
        self.close_button = ttk.Button(body, text='关闭', command=self.request_close)
        self.close_button.grid(row=4, sticky='e', pady=(18, 0))
        root.protocol('WM_DELETE_WINDOW', self.request_close)
        root.after(0, self.start)
        root.after(50, self.poll)

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
            self.message.set(f'无法打开浏览器：{error} 可复制地址后在浏览器中打开。')

    def copy_address(self):
        if self.url and not self.closing:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.url)
            self.message.set('地址已复制，可粘贴到浏览器中打开。')

    def request_close(self):
        if self.closing or self.checking_close:
            return
        self.checking_close = True
        self.close_button.configure(state='disabled')
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
                self.open_button.configure(state='disabled')
                self.copy_button.configure(state='disabled')
            else:
                self.close_button.configure(state='normal')
                self.message.set('实验仍在工作台中。请返回工作台退出实验，再关闭启动器。'
                                 if kind == 'close' else f'无法关闭服务：{result}')
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
            self.ready.grid(row=2, sticky='ew')
        elif state.phase == 'failed':
            self.status.set('启动失败')
            self.message.set(f'{state.error} 请关闭窗口后重试，或使用 nuclemu serve --no-gui。')
        self.root.after(50, self.poll)


def launch(paths=(), *, port=0, directory=None):
    """Show the launcher before discovering courses and starting its service."""
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
