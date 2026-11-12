# Nuclemu

*A Virtual Nuclear Physics Lab*

[English](README.md)

Nuclemu 是面向本科实验课的本地核物理仿真软件。当前开发版本包含 α 能损和 β 吸收实验。学生可以改变铝箔厚度，观测 α 谱的峰移。在 β 实验中，学生分别测量样品计数和环境本底，利用记录的实际曝光计算净计数率。

## 开始使用

在仓库目录使用 Python 3.11 或更高版本，运行以下命令，在浏览器中打开本地工作台：

```sh
python -m nuclemu gui
```

从目录进入实验，在装置页选择源和铝箔，开启探测器输出，然后打开对应仪器采集。需要留存的读数在仪器面板上手动保存。界面资源和实验模型均在本机运行。

也可用命令行列出实验，再测 10 秒本底和有源、4 片铝箔下的 20 秒样品计数。最后一个选项以第一段为本底计算净计数率。

```sh
python -m nuclemu list
python -m nuclemu run beta --device counter --enable-output beta_detector --step 10,source_present=0 --step 20,source_present=1,foil_count=4 --background 1
```

图形工作台和命令行共用仿真时钟、仪器模型和测量结果。实验作者可以编写受信任的 Python 模块，将新实验加入目录。交付规划还列出了后续十门实验。

## 文档

| 文档 | 内容 |
|---|---|
| [图形实验台](docs/gui.md) · [命令行](docs/cli.md) | 采集、刻度、导出以及命令行可选的扣本底操作 |
| [学生手册](docs/student.md) · [α 能损](docs/alpha.md) · [β 吸收](docs/beta.md) | 实验步骤、空白记录表与实测数据处理 |
| [教师用书](docs/teacher/README.md) · [α 能损](docs/teacher/alpha.md) · [β 吸收](docs/teacher/beta.md) | 备课、能量刻度与计数不确定度的课堂讨论 |
| [技术参考](docs/technical/README.md) · [α 能谱](docs/technical/alpha.md) · [β 计数](docs/technical/beta.md) | 仪器参数、模型适用范围和可复现的测量用例 |
| [交付规划](docs/plan.md) | 工作台的范围、交付顺序和完成条件 |
| [框架与接口](docs/architecture.md) | 实验模块、仿真时间、仪器面板和测量数据 |
| [12 个实验](docs/experiments.md) | 每项实验的物理问题、测量设计与验收要求 |

本项目采用 [GNU 通用公共许可证第 3 版](LICENSE)。
