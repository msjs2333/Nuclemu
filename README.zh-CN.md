# Nuclemu

*A Virtual Nuclear Physics Lab*

[English](README.md)

Nuclemu 是面向本科实验课的本地核物理仿真软件。学生在浏览器中操作源座、铝箔、探测器和仪器，保存读数，再用实际曝光和计数处理自己的测量数据。工作台与实验模型均在本机运行。

## 已可使用的实验

| 实验 | 可以完成的测量 | 学生资料 |
|---|---|---|
| α 粒子在铝箔中的能量损失 | 采集 1,024 道谱，选择峰区 ROI，建立两点能量刻度，改变箔厚并跟踪谱峰移动。 | [α 能损实验](docs/student/alpha.md) |
| β 射线吸收 | 用 A、B 两窗记录虚拟重复观测，分别测本底和透射计数。导出整数计数与实际曝光，在本地计算净率及不确定度。 | [β 吸收实验](docs/student/beta.md) |

目前内置这两门课。[实验目录规划](docs/design/experiments.md)与[交付规划](docs/design/plan.md)另列后续十门实验。

## 试用 0.0.1 预发布

目前尚无正式公开发布。试用可使用下列 GitHub Actions 构建产物，均来自已合并 [PR #16](https://github.com/msjs2333/Nuclemu/pull/16) 的最终提交。

登录 GitHub，打开对应构建，在页面的 **Artifacts** 区域下载指定名称的 ZIP，再解压取得安装程序或应用镜像及校验和。构建产物有保留期限，操作方法见 [GitHub 下载说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)。

| 系统与架构 | 构建与产物名 | 使用的安装包 |
|---|---|---|
| Windows x64 | [Windows 构建](https://github.com/msjs2333/Nuclemu/actions/runs/43709026349) · `Nuclemu-windows-x64` | `Nuclemu-0.0.1-windows-x64-setup.exe` |
| macOS · Intel | [macOS 构建](https://github.com/msjs2333/Nuclemu/actions/runs/43709026362) · `Nuclemu-macos-x86_64` | `Nuclemu-0.0.1-macos-x86_64.dmg` |
| macOS · Apple Silicon | [macOS 构建](https://github.com/msjs2333/Nuclemu/actions/runs/43709026362) · `Nuclemu-macos-arm64` | `Nuclemu-0.0.1-macos-arm64.dmg` |
| Linux · Debian 12 amd64 | [Linux 构建](https://github.com/msjs2333/Nuclemu/actions/runs/43709026386) · `Nuclemu-linux-amd64` | `nuclemu_0.0.1-1_amd64.deb` 或 `nuclemu-0.0.1-1-linux-amd64.tar.gz` |

包内已有 Python 和工作台资源，课机需有可用浏览器。Linux 还需备齐说明中列出的系统库。Windows 包未作发布者签名，macOS 包使用 ad-hoc 签名且尚未公证。安装步骤、已测系统、平台待验项、升级和卸载见[安装与启动](docs/guides/installation.zh-CN.md)。

### 首次启动

1. 安装对应平台的包，从开始菜单、Applications 或 Linux 应用菜单打开 **Nuclemu**。Linux 便携包在解压后的程序目录运行 `./nuclemu-desktop`。
2. 启动器显示“**已就绪**”后，点“**在浏览器中打开**”。默认不自动打开浏览器，实验期间保持启动器打开。
3. 从目录进入 α 或 β，在装置页选择源和箔片、开启探测器输出，再打开仪器开始测量。步骤与空白表格可从“**实验资料**”查阅。
4. 在仪器上点“**保存**”留存读数，再到“**实验记录**”下载所选数据或整场 `.nuclemu` 文件，带走本次实验。

采集、刻度、安全关闭与重开数据的具体操作见[工作台说明](docs/student/gui.md)。

### 从源码运行

在仓库根目录使用 Python 3.11 或更高版本，桌面启动器还需要 Tk 支持：

```sh
python -m nuclemu serve --gui
```

仅运行终端服务可用 `python -m nuclemu serve --no-gui`，再访问打印的本机地址。原有 `python -m nuclemu gui` 仍可从终端启动服务并打开浏览器。终端服务用 Ctrl+C 停止，停止前请先下载数据。终端中断不会代为保存实验。

## 命令行测量

CLI 与工作台共用仿真时钟、仪器模型和测量结果。例如先列出实验，再测 10 秒本底和有源、4 片铝箔下的 20 秒 β 计数。最后一个选项以第一段为本底计算净率。

```sh
python -m nuclemu list
python -m nuclemu run beta --device counter --enable-output beta_detector --step 10,source_present=0 --step 20,source_present=1,foil_count=4 --background 1
```

脚本测量、可信课程目录、刻度和文件导入导出见[命令行说明](docs/guides/cli.md)。

## 开发课程

课程作者可通过 `--path` 加入受信任的 Python 模块，复用已有装置和仪器接口。可先读[课程接口与框架](docs/design/architecture.md)，再参考[可运行的课程示例](examples/courses)。例如核对示例定义并载入工作台：

```sh
python -m nuclemu validate --path examples/courses
python -m nuclemu serve --gui --path examples/courses
```

课程模块会执行 Python 代码，只加载自己信任的目录。物理模型、单位、采集语义与可复验用例见[技术参考](docs/technical/README.md)。

## 文档入口

[文档总目录](docs/README.md)

| 读者或任务 | 入口 |
|---|---|
| 学生实验 | [学生手册](docs/student/README.md) · [α 能损](docs/student/alpha.md) · [β 吸收](docs/student/beta.md) · [工作台操作](docs/student/gui.md) |
| 教师备课 | [教师用书](docs/teacher/README.md) · [α 能损](docs/teacher/alpha.md) · [β 吸收](docs/teacher/beta.md) |
| 课程开发与维护 | [技术参考](docs/technical/README.md) · [框架与接口](docs/design/architecture.md) · [CLI](docs/guides/cli.md) |
| 范围与后续实验 | [交付规划](docs/design/plan.md) · [实验目录规划](docs/design/experiments.md) |
| 美术贡献 | [贡献指南](docs/art/art-contributing.md) · [资产说明](docs/art/art-assets.md)（英文） |

本项目采用 [GNU 通用公共许可证第 3 版](LICENSE)。
