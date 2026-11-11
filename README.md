# Nuclemu

*A Virtual Nuclear Physics Lab*

[中文](#中文) · [English](#english)

## 中文

Nuclemu 是一个面向本科实验课的核物理仿真软件项目，目前处于设计阶段。目标是在一台电脑上完成从调节装置到取得读数的实验过程。例如，在 α 能损实验中，学生可以改变铝箔厚度、采集能谱，再用刻度后的峰位估算粒子损失的能量。

规划中的工作台包含 12 个实验。各实验共享可调速的物理时钟，并按实际装配的仪器提供面板。实验作者可以通过模块接口复用源、材料和探测器。图形界面和命令行使用同一套模型，测量结果可按需导出为计数表、谱或刻度文件。

| 文档 | 内容 |
|---|---|
| [交付规划](docs/plan.md) | 工作台的范围、交付顺序和完成条件 |
| [框架与接口](docs/architecture.md) | 实验模块、仿真时间、仪器面板和测量数据 |
| [12 个实验](docs/experiments.md) | 每项实验的物理问题、测量设计与验收要求 |

本项目采用 [GNU 通用公共许可证第 3 版](LICENSE)。

## English

Nuclemu is a nuclear physics simulation project for undergraduate laboratories, currently in the design stage. The goal is to let students set up a measurement and obtain instrument readings on a single computer. In the alpha energy-loss experiment, for example, a student varies the thickness of an aluminium foil, records a spectrum and uses the calibrated peak position to estimate how much energy the particles lost.

The workbench is planned around 12 experiments. Each experiment uses a common simulation clock with adjustable playback speed and exposes panels for the instruments in its setup. Experiment authors will be able to reuse sources, materials and detectors through a module interface. The GUI and CLI will share the same models and support selective export of count tables, spectra and calibrations.

The design documents are written in Chinese.

| Document | Contents |
|---|---|
| [Delivery plan](docs/plan.md) | Scope, delivery sequence and acceptance criteria |
| [Architecture and interfaces](docs/architecture.md) | Experiment modules, simulation time, instrument panels and measurement data |
| [Experiment catalogue](docs/experiments.md) | Physics questions, measurement designs and requirements for all 12 experiments |

Nuclemu is licensed under the [GNU General Public License, version 3](LICENSE).
