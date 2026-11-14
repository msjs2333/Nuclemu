# Windows x64 离线目录样包

解压整个目录，在含有 `nuclemu.exe` 的目录打开 PowerShell。运行 `.\nuclemu.exe serve --gui`，待窗口显示“已就绪”，点“在浏览器中打开”。关闭浏览器页面后，可用同一按钮回到实验。结束时先在工作台退出实验，再关闭启动器。命令行用户可以运行 `.\nuclemu.exe serve --no-gui`，在浏览器打开终端打印的本机地址，用 Ctrl+C 停止服务。

复制样包时保留同级的 `_internal` 目录，其中包括 Python、Tk、SQLite、两门实验和工作台资源。学生机只需已有可运行工作台的浏览器。当前样包由终端启动，桌面快捷方式和系统卸载入口随安装程序交付。

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
