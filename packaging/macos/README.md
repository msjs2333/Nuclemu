# macOS 离线应用

Intel 使用 `Nuclemu-0.0.1-macos-x86_64.dmg`，Apple Silicon 使用 `Nuclemu-0.0.1-macos-arm64.dmg`。打开 DMG，把 **Nuclemu.app** 拖入 **Applications**，再从应用程序启动。应用包含 Python、Tcl/Tk、SQLite、两门课程及已构建的工作台资源；学生机无需 Python、Node 或联网安装依赖。

命令行位于 `/Applications/Nuclemu.app/Contents/MacOS/nuclemu-cli`。例如：

```sh
/Applications/Nuclemu.app/Contents/MacOS/nuclemu-cli serve --no-gui
```

终端就绪后打印本机地址，以 Ctrl+C 停止。`serve --gui` 使用同一用户的桌面启动器。升级前退出启动器和独立终端服务，用新应用替换旧 `.app`。卸载只移除 `.app`；`~/.nuclemu` 中的启动器偏好和工作台存储、用户另存的实验文件保留。

本轮使用 ad-hoc 代码签名，**未使用 Developer ID 签名、未公证**。下载隔离属性与 Gatekeeper 首次打开、Finder 冷启动、系统保存窗口和真实浏览器交接须在桌面机器单列实测。runner 的 CLI 验证不能替代这些项目，也不能据构建机器推断最低兼容系统。

## 构建与 runner 交接

在 macOS 原生 runner 的仓库根目录运行 `bash packaging/macos/build.sh x86_64` 或 `bash packaging/macos/build.sh arm64`。Intel 对应 `macos-15-intel`，Apple Silicon 对应 `macos-15`。脚本使用已签入的生产前端，不另行重建。

构建阶段从 python.org 下载固定 CPython 3.14.10 universal2 安装包，核 SHA-256 与安装包签名，安装后用其创建隔离环境，固定 PyInstaller 6.20.0、hooks 2026.10。各架构原生冻结，包内 CLI 与图形入口共用运行时。`--bundle-check` 仅供验包，报告包内 Python/Tcl/Tk/SQLite 与架构。

产物在 `dist/macos/<arch>/`：主 DMG、`SHA256SUMS`、`build-info.json`、`runtime-check.json`。另有 `-r1.dmg`，它是具有不同 bundle build 编号和过时资源的早期**包修订测试载体**；物理实现、源码版本与主包相同，不将替换该修订称为跨产品版本升级。

```sh
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14 \
  packaging/macos/smoke.py \
  --dmg dist/macos/arm64/Nuclemu-0.0.1-macos-arm64.dmg \
  --output build/macos-smoke-arm64
```

smoke 驱动只用 runner 的 Python 标准库；应用运行和实验处理全部调用冻结 CLI，不导入源码。它挂载 DMG 后把 `.app` 复制到隔离的中文及空格目录，卸载镜像，再以最小 PATH、独立 HOME 运行；检查代码签名、Mach-O 不引用构建机非系统绝对路径、实际 Tcl、目录、资源、α 谱及刻度、β 双窗文件、SIGINT 返回与端口释放。随后以修订 2 替换修订 1、确认过时资源消失、旧文件可读，删除应用后确认偏好、本地工作台目录和实验文件字节不变。

smoke 无下载，但不改变 runner 全局网络；真正断网及无开发工具的普通用户、Finder、原生保存、Gatekeeper 仍需独立实测。每次结果以 `report.json` 和构建环境为准，脚本存在不表示已通过。

依据：[GitHub runner 镜像](https://github.com/actions/runner-images)、[Python 3.14.10](https://www.python.org/downloads/release/python-31410/)、[PyInstaller macOS 说明](https://pyinstaller.org/en/stable/feature-notes.html)。
