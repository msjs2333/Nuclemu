# Windows x64 离线安装与目录包

安装程序为 `Nuclemu-0.0.1-windows-x64-setup.exe`，安装时无需联网。默认仅为当前用户安装，也可选择为所有用户安装（需要管理员权限）。开始菜单的 **Nuclemu** 打开桌面启动器；命令行程序为安装目录中的 `nuclemu.exe`，不修改系统 PATH。

更新前先保存实验并关闭 Nuclemu 的桌面和终端服务。再次运行安装程序会沿用已有安装范围与目录。卸载可从 Windows“已安装的应用”进入；卸载程序不会主动删除用户目录中的 `.nuclemu` 设置、工作台数据或用户另存的实验文件。只有上次安装登记的旧程序文件会在升级时清理；建议将实验文件另存到文档或移动存储设备。

以下说明也适用于完整解压后直接运行的目录包。

解压整个目录，双击 **`Nuclemu-Desktop.exe`**。待窗口显示“已就绪”，点“在浏览器中打开”。再次双击会唤回同一个启动器。关闭浏览器标签页后，可用启动器回到当前实验。

要结束实验，关闭启动器即可。选择“保存并关闭”后，在系统文件窗口选定 `.nuclemu` 的存放位置。文件包含实验设置和已缓存的读数。如果还要带走仪器上的当前读数，选择“取消”，回仪器保存读数后再关闭。“放弃并关闭”直接退出。没有活动实验时，启动器直接关闭。

在“设置”中可以选择自动分配端口、指定固定端口，以及每次启动后是否自动打开默认浏览器。默认使用自动端口，手动打开浏览器。保存设置后，当前实验仍可在原地址继续。下次启动会使用新设置；遇到端口占用时，在原窗口修改端口后点“重试”即可。

命令行入口为同目录的 `nuclemu.exe`。运行 `.\nuclemu.exe serve --gui` 可以打开或唤回桌面启动器；运行 `.\nuclemu.exe serve --no-gui` 可启动独立的终端服务，访问打印的本机地址，用 Ctrl+C 停止。复制样包时保留同级的 `_internal` 目录，其中包括两个入口共用的 Python、Tk、SQLite、两门实验和工作台资源。学生机只需已有可运行工作台的浏览器。目录包本身不注册开始菜单或卸载项；安装程序提供这些入口。

## 构建安装程序

先按下节生成目录载荷，再用 [Inno Setup 6.7.4](https://github.com/jrsoftware/issrc/releases/tag/is-6_7_4) 编译。编译器只用于构建，不随程序安装。可在一次性 Windows Sandbox 中安装编译器并执行本脚本，避免改变宿主安装状态。

```powershell
.\packaging\windows\build-installer.ps1 -Compiler 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
```

默认读取 `dist/Nuclemu`，生成 `dist/release/Nuclemu-0.0.1-windows-x64-setup.exe` 及记录编译器、载荷和安装器 SHA256 的 manifest。脚本将载荷复制到临时本地目录，用本页更新包内 README，并生成只登记程序文件的升级台账；不会修改原目录载荷。安装程序不下载运行时。中文翻译和许可来源见 [THIRD-PARTY.md](THIRD-PARTY.md)。

`verify-installer.ps1` 只供一次性测试机使用，要求明确的 `ExpectedComputerName`，覆盖普通/全机范围、旧候选升级、淘汰程序文件与未登记用户文件、偏好/工作台数据、αβ重开、入口、运行保护、卸载与重装。`sandbox-acceptance.ps1` 的固定映射路径和新建测试账户仅适用于独占沙箱，不应在学生机运行。普通账户对测试输入只读，只有其结果目录可写。

Windows PowerShell 5.1 按 BOM 识别含中文源码的测试脚本；`verify-installer.ps1` 因此使用 UTF-8 BOM。构建和测试仅设置各自进程的执行策略，不改变学生电脑的系统编码或执行策略。

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
