# Windows x64 离线目录样包

解压整个目录，双击 **`Nuclemu-Desktop.exe`**。待窗口显示“已就绪”，点“在浏览器中打开”。再次双击会唤回同一个启动器。关闭浏览器标签页后，可用启动器回到当前实验。

要结束实验，关闭启动器即可。选择“保存并关闭”后，在系统文件窗口选定 `.nuclemu` 的存放位置。文件包含实验设置和已缓存的读数。如果还要带走仪器上的当前读数，选择“取消”，回仪器保存读数后再关闭。“放弃并关闭”直接退出。没有活动实验时，启动器直接关闭。

在“设置”中可以选择自动分配端口、指定固定端口，以及每次启动后是否自动打开默认浏览器。默认使用自动端口，手动打开浏览器。保存设置后，当前实验仍可在原地址继续。下次启动会使用新设置；遇到端口占用时，在原窗口修改端口后点“重试”即可。

命令行入口为同目录的 `nuclemu.exe`。运行 `.\nuclemu.exe serve --gui` 可以打开或唤回桌面启动器；运行 `.\nuclemu.exe serve --no-gui` 可启动独立的终端服务，访问打印的本机地址，用 Ctrl+C 停止。复制样包时保留同级的 `_internal` 目录，其中包括两个入口共用的 Python、Tk、SQLite、两门实验和工作台资源。学生机只需已有可运行工作台的浏览器。开始菜单和卸载入口随以后的安装程序交付。

## 从源码构建

在 Windows x64 的仓库根目录运行。该样包使用 CPython 3.12.13 x64（含 Tcl/Tk）、PyInstaller 6.20.0 和 pyinstaller-hooks-contrib 2026.10。使用干净的虚拟环境可避免收进构建机上其他项目的包。仓库已经包含生产前端；若修改了前端，先在 `frontend` 目录运行 `npm ci` 与 `npm run build`。

```powershell
py -3.12 -m venv build\desktop-venv
build\desktop-venv\Scripts\python -m pip install PyInstaller==6.20.0 pyinstaller-hooks-contrib==2026.10
build\desktop-venv\Scripts\python -m PyInstaller --clean --noconfirm packaging\windows\nuclemu.spec
dist\Nuclemu\nuclemu.exe validate
```

## 验证离线样包

将应用目录和本页同目录的 `smoke.ps1` 复制到测试机。下面的命令要求输出目录尚不存在，便于将每次验证的实验文件和服务日志分开留存。

```powershell
.\smoke.ps1 -Executable .\Nuclemu\nuclemu.exe -OutputDirectory "$env:TEMP\NuclemuReadings-01"
```

脚本用包内 CLI 保存 3 s 的 α 谱及两点刻度，再保存相同曝光的 β 双窗读数。它从新工作目录启动 HTTP 服务，读取两课目录和工作台资源，并把文件载入服务。α 逐道对照 1,024 个计数；β 分别对照 A 的三个完整窗、B 的一个部分窗和两边总计数。`AEL.nuclemu`、`BABS.nuclemu` 可继续用于浏览器、其他平台和将来安装版的交叉验证。端口释放、原生窗口和浏览器下载需分别验收。

### 检查桌面缩放

从目录包启动 `serve --gui`，在 Windows 显示设置中核对该屏的缩放比例。检查中文状态、完整地址、按钮边界和键盘焦点。若有两块不同缩放的显示器，将同一个窗口拖到另一屏，再拖回来。字号和间距应随所在屏幕重算，回到原屏后尺寸应恢复；地址、复制、打开和关闭操作在两屏上都应可用。

Windows 可执行文件在启动清单中请求每显示器 DPI 感知。发布验收需实际运行冻结后的窗口，并记录系统返回的窗口 DPI。150% 对应 144 DPI，200% 对应 192 DPI。[Windows 的 DPI 声明](https://learn.microsoft.com/windows/win32/hidpi/setting-the-default-dpi-awareness-for-a-process)
