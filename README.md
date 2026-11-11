# Nuclemu

*A Virtual Nuclear Physics Lab*

[中文](#中文) · [English](#english)

## 中文

Nuclemu 是面向本科实验课的本地核物理仿真软件。当前开发版本包含 α 能损和 β 吸收实验。学生可以改变铝箔厚度，观测 α 谱的峰移，或比较 β 计数器在不同厚度下的净计数率。

在仓库目录使用 Python 3.11 或更高版本运行以下命令。示例先测 10 秒本底，再叠加 4 片铝箔测量 20 秒，并以第一段作为本底计算净计数率。

```sh
python -m nuclemu list
python -m nuclemu run beta --step 10,source_present=0 --step 20,source_present=1,foil_count=4 --background 1
```

安装了 Tk 的 Python 可用 `python -m nuclemu gui` 打开图形实验台，在同一窗口切换实验、采集谱或计数并导出。

规划中的工作台包含 12 个实验。各实验共享可调速的物理时钟，并按实际装配的仪器提供面板。实验作者可以通过模块接口复用源、材料和探测器。图形界面和命令行使用同一套模型，测量结果可按需导出为计数表、谱或刻度文件。

| 文档 | 内容 |
|---|---|
| [图形实验台](docs/gui.md) · [命令行](docs/cli.md) | 采集、刻度、扣本底和导出操作 |
| [α 能损](docs/alpha.md) · [β 吸收](docs/beta.md) | 两门实验的物理依据与适用范围 |
| [交付规划](docs/plan.md) | 工作台的范围、交付顺序和完成条件 |
| [框架与接口](docs/architecture.md) | 实验模块、仿真时间、仪器面板和测量数据 |
| [12 个实验](docs/experiments.md) | 每项实验的物理问题、测量设计与验收要求 |

本项目采用 [GNU 通用公共许可证第 3 版](LICENSE)。

## English

Nuclemu is a local nuclear physics simulator for undergraduate laboratories. The development version includes alpha energy loss and beta absorption. Students can vary an aluminium foil's thickness and measure either the shift in an alpha spectrum or the change in the beta counter's net rate.

From the repository directory, use Python 3.11 or later. The example measures the background for 10 seconds, then measures a sample behind four foils for 20 seconds and reports the background-subtracted rate.

```sh
python -m nuclemu list
python -m nuclemu run beta --step 10,source_present=0 --step 20,source_present=1,foil_count=4 --background 1
```

With Tk installed, run `python -m nuclemu gui` to open the workbench. You can switch between experiments, acquire spectra and counts, and export measurements from the same window.

The workbench is planned around 12 experiments. Each experiment uses a common simulation clock with adjustable playback speed and exposes panels for the instruments in its setup. Experiment authors will be able to reuse sources, materials and detectors through a module interface. The GUI and CLI will share the same models and support selective export of count tables, spectra and calibrations.

The design documents are written in Chinese.

| Document | Contents |
|---|---|
| [Workbench](docs/gui.md) · [Command line](docs/cli.md) | Acquisition, calibration, background subtraction and export |
| [Alpha energy loss](docs/alpha.md) · [Beta absorption](docs/beta.md) | Physical models and limits of the two experiments |
| [Delivery plan](docs/plan.md) | Scope, delivery sequence and acceptance criteria |
| [Architecture and interfaces](docs/architecture.md) | Experiment modules, simulation time, instrument panels and measurement data |
| [Experiment catalogue](docs/experiments.md) | Physics questions, measurement designs and requirements for all 12 experiments |

Nuclemu is licensed under the [GNU General Public License, version 3](LICENSE).
