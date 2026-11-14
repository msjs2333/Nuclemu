# 安装与启动 Nuclemu

[English](installation.md)

0.0.1 桌面包正在[草稿 PR #16](https://github.com/msjs2333/Nuclemu/pull/16)中准备。试用时，请使用与操作系统、架构相符的候选包，并一起查看该包的验证记录。本页说明候选版本的用法，目前尚未正式发布。

桌面包包含运行时、实验和工作台资源，课机只需已有桌面浏览器，无须另装 Python 或 Node.js。安装后，工作台可断网在本机运行。

## Windows

安装候选包为 `Nuclemu-0.0.1-windows-x64-setup.exe`，尚未作发布者签名。运行后选择安装范围：默认仅当前用户，也可用管理员权限为所有用户安装。安装后从开始菜单打开 **Nuclemu**；CLI 为安装目录中的 `nuclemu.exe`。

升级前保存实验，关闭启动器和终端服务，再运行新安装程序，沿用已有安装范围。卸载时从 Windows 的“已安装的应用”中找到 Nuclemu。若提示程序仍在运行，先完成保存并关闭，再重试；安装程序不会替你结束正在进行的实验。

Windows x64 目录样包已在 Windows 11 验证，包括断网的 Windows Sandbox。使用目录样包时，完整解压，双击 `Nuclemu-Desktop.exe`，保留同级的 `nuclemu.exe` 和 `_internal`。详见[Windows 包说明](../packaging/windows/README.md)。

同一最终安装包已在 Windows 11 沙箱通过普通账户的当前用户安装和管理员账户的全机安装检查。Windows 10 及更旧系统仍待验，Windows 7 SP1 是兼容目标，尚不能作为已验证的最低版本。

## macOS

Intel 候选包名为 `Nuclemu-0.0.1-macos-x86_64.dmg`，Apple Silicon 为 `Nuclemu-0.0.1-macos-arm64.dmg`。打开对应 DMG，将 `Nuclemu.app` 拖入 Applications，再从 Applications 启动。升级前关闭启动器，再用新应用替换旧应用；卸载时移除 Applications 中的 `Nuclemu.app`，保留自己的实验文件。

应用内的 CLI 路径为：

```sh
/Applications/Nuclemu.app/Contents/MacOS/nuclemu-cli serve --no-gui
```

Intel 候选包已在 macOS 15.7.9、arm64 候选包已在 macOS 15.8.2 原生 runner 通过挂载、复制安装、CLI 与实验文件检查、较早包修订的覆盖替换，以及卸载后保留用户数据检查。这些是已测环境，不代表最低支持版本。候选应用使用 ad-hoc 签名，尚无 Developer ID 签名和公证。下载应用的首次打开（含 Gatekeeper）、Finder 启动和系统保存窗口仍需桌面实测。smoke 阶段无下载，但未关闭 runner 网络。完整验证范围见[交付记录](desktop-release-delivery.md)。

## Linux

候选包以 Debian 12、amd64、glibc 2.36 为基线，文件名为 `nuclemu_0.0.1-1_amd64.deb` 和 `nuclemu-0.0.1-1-linux-amd64.tar.gz`。便携 CLI 已在断网、无系统 Python 或 Node.js 的最小容器中通过非 root 检查。Debian 包修订0→1覆盖、Xvfb 下的菜单入口、卸载后保留偏好与实验文件，以及移动便携目录后重开 Windows 两份实验样本，则在另一带测试驱动的断网 Debian 容器中验证。范围限于 Debian 12 amd64，其他发行版待验，详见[交付记录](desktop-release-delivery.md)。

在 `.deb` 所在目录执行安装或升级：

```sh
sudo dpkg -i ./nuclemu_0.0.1-1_amd64.deb
```

从应用菜单打开 Nuclemu，或运行 `nuclemu-desktop`。已在 Xvfb、Openbox 虚拟 X11 容器中独立核对安装包从桌面菜单启动，并自动在默认 Firefox ESR 153.7.0 中打开工作台；实体桌面与 Wayland 会话仍待验。终端命令为 `nuclemu`，例如 `nuclemu serve --no-gui`。程序运行时位于 `/opt/nuclemu`。关闭 Nuclemu 后，可卸载程序包：

```sh
sudo dpkg -r nuclemu
```

压缩包可完整解压到用户可写目录，在其中的 `nuclemu-0.0.1` 目录运行 `./nuclemu-desktop` 或 `./nuclemu serve --no-gui`，保留同级的 `_internal`。目录包无需管理员账户；升级时解压到新目录，卸载时先关闭服务，再移除该程序目录。

两种格式均需系统已有 `libc6 >= 2.36`、`libx11-6`、`libxext6`、`libxft2`、`libxrender1`、`libfontconfig1`、`libfreetype6`、`libexpat1`、`zlib1g`。桌面使用还需 X11 或 XWayland、字体和浏览器，建议准备 `xdg-utils` 及中文字体。断网部署前，由管理员备齐这些组件；包内携带 Python 和 Tk，但不携带 glibc。详见[Linux 包说明](../packaging/linux/README.md)。

## 打开工作台

从桌面入口启动 Nuclemu。启动器显示“已就绪”后，点“在浏览器中打开”。实验期间保持启动器打开。关闭浏览器标签页不会停止本机服务或结束实验，可从启动器再次进入。

默认自动分配端口，自动打开浏览器为关闭。在“设置”中可指定固定端口，或开启启动后自动打开浏览器。保存设置后，下次启动或重试时生效，当前实验继续使用原地址。端口被占用时，改用另一个端口并重试；也可复制窗口中的本机链接到浏览器。

从目录进入课程，在装置页设置源和箔片、开启探测输出，再打开仪器。实验步骤和空白记录表在“实验资料”中，操作方法见[工作台说明](gui.md)。

## 保存实验并关闭

在仪器上点“保存”，留存需要的读数；在“实验记录”下载所选记录或整场 `.nuclemu` 文件。

有活动实验时，关闭启动器会提供“保存并关闭”“放弃并关闭”“取消”。选择保存后，在系统文件窗口选定位置，写入整场文件成功后才停止服务。取消选址或写入失败时，实验仍可返回或重试。

整场文件保留设置、轮次信息与已经手动留存的读数。例如3 s时保存、继续测到5 s，保存并关闭仍只带走3 s读数。需要5 s读数时，先取消关闭，回仪器保存，再关闭。可从目录载入 `.nuclemu`，核对已保存的数据。

## 升级与卸载

升级或卸载前，先保存需要的读数，把整场实验另存到自己管理的文件夹，再关闭启动器。若另开了终端服务，也用 Ctrl+C 停止。

把 `.nuclemu`、CSV、JSON 文件保存在程序目录之外。启动器偏好按用户放在 `~/.nuclemu/launcher.json`，Windows上的 `~` 为用户目录；本地工作台存储在 `~/.nuclemu/workbench/`。这些内部文件不能代替已导出的实验文件。

候选安装方案在卸载程序时保留用户偏好、本地工作台存储和另外保存的实验。安装、升级与卸载按平台分别记录验证结果。目录样包可把新版本解压到另一目录，启动后重开一份旧实验核对，再停用旧程序目录。

## 命令行与源码运行

包内 CLI 与桌面启动器使用相同的实验和文件格式。在 Windows 目录样包中，可从解压目录运行：

```powershell
.\nuclemu.exe serve --gui
.\nuclemu.exe serve --no-gui
```

`serve --gui` 打开或唤回桌面启动器；`serve --no-gui` 另起前台终端服务，打印本机地址，不打开浏览器，用 Ctrl+C 停止。终端中断不会代为保存实验，请先下载数据。两种模式必须选其一。

源码使用者可在仓库根目录，以 Python 3.11 或更高版本运行：

```sh
python -m nuclemu serve --gui
```

桌面模式需要 Python 含 Tk 支持。仅运行终端服务可用 `python -m nuclemu serve --no-gui`。原有 `python -m nuclemu gui` 仍可在终端管理服务并打开浏览器。脚本测量见[命令行说明](cli.md)。
