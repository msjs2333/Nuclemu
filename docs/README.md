# Nuclemu 文档

第一次使用可从[安装与启动](guides/installation.zh-CN.md)开始。启动器显示就绪后，在默认浏览器中选择课程。英文安装说明见 [Install and start Nuclemu](guides/installation.md)。

## 做实验与备课

| 要做的事 | 从这里开始 |
| --- | --- |
| 测量 α 粒子穿过铝箔后的能量变化 | [α 实验](student/alpha.md)包含参考谱刻度、加箔测量步骤和记录表。 |
| 测量 β 射线透射计数与本底 | [β 实验](student/beta.md)说明双窗计数、曝光和净计数率的处理。 |
| 操作仪器、保存读数或重开实验 | [工作台操作](student/gui.md)与[装置接线](student/apparatus-overview.md)。 |
| 准备一堂实验课 | [教师教学用书](teacher/README.md)按实验给出课堂安排、测点和讨论题。 |
| 用脚本重复测量 | [命令行指南](guides/cli.md)含固定种子、分段采集和文件读回示例。 |

[学生实验手册](student/README.md)中的 α、β 两章也是工作台左栏“实验资料”的正文。

## 编写课程与维护软件

- [实验技术参考](technical/README.md)收录两门课程的模型、单位和适用范围。核对采集轮次及导出字段时可查[测量流程](technical/measurement-workflow.md)和[文件交换](technical/exchange.md)。
- 从[课程架构与接口](design/architecture.md)和[可运行的课程模块](../examples/courses/)了解如何接入新实验。
- 图像贡献者可查阅[绘图规范](art/art-contributing.md)、[素材索引](art/art-assets.md)和[工作台图像来源](art/runtime-artwork.md)。
- [桌面包验收记录](release/desktop-release-delivery.md)列有各平台已测范围。[工作台验收](release/workbench-acceptance.md)记录装置、仪器和文件操作的检查场景。

## 设计与规划

当前可运行的课程为 α 和 β。[实验设计目录](design/experiments.md)列出规划中的 12 门实验，[交付规划](design/plan.md)说明开发顺序。[远景系列](vision/README.md)收录课堂部署、课程编排和模型扩展的设想。
