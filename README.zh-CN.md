# Nuclemu

*A Virtual Nuclear Physics Lab*

[English](README.md)

Nuclemu 是面向本科实验课的本地核物理仿真软件。当前开发版本包含 α 能损和 β 吸收实验。学生可以改变铝箔厚度，观测 α 谱的峰移，或比较 β 计数器在不同厚度下的净计数率。

## 开始使用

在仓库目录使用 Python 3.11 或更高版本。安装了 Tk 的 Python 可用以下命令打开图形工作台：

```sh
python -m nuclemu gui
```

也可用命令行列出实验，再测 10 秒本底和有源、4 片铝箔下的 20 秒样品计数。最后一个选项以第一段为本底计算净计数率。

```sh
python -m nuclemu list
python -m nuclemu run beta --step 10,source_present=0 --step 20,source_present=1,foil_count=4 --background 1
```

图形工作台和命令行共用仿真时钟、仪器模型和测量结果。实验作者可以编写受信任的 Python 模块，将新实验加入目录。交付规划还列出了后续十门实验。

## 文档

| 文档 | 内容 |
|---|---|
| [图形实验台](docs/gui.md) · [命令行](docs/cli.md) | 采集、刻度、扣本底和导出操作 |
| [α 能损](docs/alpha.md) · [β 吸收](docs/beta.md) | 两门实验的物理依据与适用范围 |
| [交付规划](docs/plan.md) | 工作台的范围、交付顺序和完成条件 |
| [框架与接口](docs/architecture.md) | 实验模块、仿真时间、仪器面板和测量数据 |
| [12 个实验](docs/experiments.md) | 每项实验的物理问题、测量设计与验收要求 |

本项目采用 [GNU 通用公共许可证第 3 版](LICENSE)。
