"""Event-driven native close confirmation; service transactions run elsewhere."""

from .desktop_dpi import window_dpi, work_area


class ExitWindow:
    def __init__(self, launcher, context):
        import tkinter as tk
        from tkinter import font
        from pathlib import Path
        import sys
        from .desktop import INK, MUTED
        from .desktop_chrome import blend_windows_caption

        self.launcher, self.context = launcher, context
        self.busy = False
        self.completed = False
        self.dpi = None
        self.root = tk.Toplevel(launcher.root, background='white')
        self.root.title('Nuclemu 关闭实验')
        self.root.transient(launcher.root)
        self.root.resizable(False, False)
        if sys.platform == 'win32':
            self.root.iconbitmap(str(Path(__file__).with_name('static') / 'nuclemu.ico'))
        elif hasattr(launcher, '_icon_image'):
            self.root.iconphoto(False, launcher._icon_image)
        self.root.protocol('WM_DELETE_WINDOW', self.cancel)
        self.root.bind('<Escape>', lambda event: (self.cancel(), 'break')[1])
        self.root.bind('<Return>', lambda event: (self.cancel(), 'break')[1])
        self.root.bind('<Destroy>', self._destroyed, add='+')
        self.fonts = {name: font.Font(self.root, family=launcher.fonts['body'].actual('family'),
            weight='bold' if name == 'brand' else 'normal') for name in ('body', 'brand')}
        self.body = tk.Frame(self.root, background='white')
        self.body.pack(fill='both', expand=True)
        self.body.columnconfigure(0, weight=1)
        self.heading = tk.Label(self.body, text='关闭前是否保存实验？',
            font=self.fonts['brand'], foreground=INK, background='white', anchor='w')
        self.heading.grid(row=0, sticky='ew')
        text = ('当前未保存的读数不会随文件带走。\n要保留这些读数，请取消后在仪器上保存。' if context.has_uncached
                else '该实验为只读，可另存一份后关闭。' if context.readonly
                else '')
        self.description = tk.Label(self.body, text=text, font=self.fonts['body'],
            foreground=MUTED, background='white', justify='left', anchor='w')
        self.description.grid(row=1, sticky='ew')
        self.message = tk.StringVar()
        self.message_label = tk.Label(self.body, textvariable=self.message,
            font=self.fonts['body'], foreground=MUTED, background='white', justify='left', anchor='w')
        self.message_label.grid(row=2, sticky='ew')
        self.actions = tk.Frame(self.body, background='white')
        self.actions.grid(row=3, sticky='e')
        self.save_button = launcher.button(self.actions, '保存并关闭', self.save, primary=True)
        self.discard_button = launcher.button(self.actions, '放弃并关闭', lambda: launcher.close_action('discard'))
        self.cancel_button = launcher.button(self.actions, '取消', self.cancel)
        self.buttons = (self.save_button, self.discard_button, self.cancel_button)
        self.discard_button.configure(foreground='#9b2c21', activeforeground='#9b2c21')
        for column, button in enumerate(self.buttons):
            button.configure(font=self.fonts['body'])
            button.shell.grid(row=0, column=column)
        self._apply_dpi()
        self.root.geometry(f'+{launcher.root.winfo_rootx() + (launcher.root.winfo_width() - self.root.winfo_width()) // 2}'
                           f'+{launcher.root.winfo_rooty() + launcher.px(24)}')
        self.root.update_idletasks()
        self.blended_caption = blend_windows_caption(self.root)
        self.root.bind('<Configure>', self._configured, add='+')

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
        self.description.configure(wraplength=px(452))
        self.description.grid_configure(pady=(0, px(20)))
        if not self.description.cget('text'):
            self.description.grid_remove()
        self.message_label.configure(wraplength=px(452))
        self.message_label.grid_configure(pady=(0, px(16)))
        if not self.message.get():
            self.message_label.grid_remove()
        for column, button in enumerate(self.buttons):
            button.configure(padx=px(16), pady=px(8))
            button.pack_configure(padx=px(1), pady=px(1))
            button.shell.grid_configure(padx=(px(12) if column else 0, 0))
        if self.completed:
            self.save_button.shell.grid_remove()
            self.discard_button.shell.grid_remove()
        self.root.update_idletasks()
        width, height = work_area(self.root)
        self.root.geometry(f'{min(max(px(500), self.root.winfo_reqwidth()), width)}x'
                           f'{min(self.root.winfo_reqheight(), height)}')

    def activate(self):
        if self.launcher._choosing_path:
            return
        self.root.deiconify()
        self.root.lift()
        self.cancel_button.focus_set()

    def set_busy(self, busy):
        self.busy = busy
        for button in self.buttons:
            self.launcher._enable(button, not busy)
        self.discard_button.configure(foreground='#9b2c21', activeforeground='#9b2c21')
        if busy:
            self.notice('正在处理，请稍候…')

    def notice(self, text, *, error=False):
        self.message.set(text)
        self.message_label.configure(foreground='#9b2c21' if error else '#46525b')
        self.message_label.grid()
        self._apply_dpi()

    def save(self):
        if self.busy:
            return
        from tkinter.filedialog import asksaveasfilename
        self.set_busy(True)
        self.launcher._choosing_path = True
        try:
            path = asksaveasfilename(parent=self.root, title='保存实验文件',
                initialfile=self.context.filename, defaultextension='.nuclemu',
                filetypes=[('Nuclemu 实验文件', '*.nuclemu')])
        except Exception as error:
            self.notice(f'无法选择保存位置：{error}', error=True)
            return
        finally:
            self.launcher._choosing_path = False
            self.set_busy(False)
        if not path:
            self.notice('未选择文件。可重试保存，或取消关闭返回实验。')
            self.cancel_button.focus_set()
            return
        self.launcher.close_action('save', path)

    def cancel(self):
        if self.completed:
            self.launcher._closing_service()
        elif not self.busy:
            self.launcher.close_action('cancel')

    def saved(self, warning):
        self.completed = True
        self.set_busy(False)
        self.heading.configure(text='文件已保存')
        self.description.configure(text=warning)
        self.description.grid()
        self.message.set('')
        self.save_button.shell.grid_remove()
        self.discard_button.shell.grid_remove()
        self.cancel_button.configure(text='关闭')
        self._apply_dpi()
        self.cancel_button.focus_set()

    def destroy(self):
        self.root.destroy()

    def _destroyed(self, event):
        if event.widget == self.root:
            self.launcher.close_window = None
