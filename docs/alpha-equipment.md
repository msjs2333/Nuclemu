# α 器材、接口与联调读数

本页供课程作者、GUI 和 CLI 维护者核对器材与数据。学生步骤见[α 能损](alpha.md)，公开射程依据及模型近似见[模型参考](model-reference.md#alpha)。以下 Python 入口已实现；新的图形操作与缓存文件入口仍按[测量流程](measurement-workflow.md)联调，不把未保存的当前道谱当作已保存快照。

## 器材与端口

| 部件 ID | 可调项或绑定 | 约定 |
| --- | --- | --- |
| `source` | `source_present`：0 空源座，1 三峰参考源（默认） | 选取 5.155、5.486、5.805 MeV 三条主线。模型无本底，空源输出零计数；不是探测器电源开关。 |
| `foil` | `foil_spec_um`：1 或 2 µm/片，默认 1；`foil_count`：整数 0–40，默认 0 | 同规格均匀纯 Al 薄片，0 片为空架。规格是课程教学设定，不代表材料实测证书。 |
| `detector` | `Component.output="alpha_detector"` | 硅探测器的独立输出开关。没有绑定 `device`，不会被当成 MCA 面板入口。 |
| `mca` | `Component.device="mca"`、`Device.input="alpha_detector"` | 1024 道，独立采集门；Nuclemu 文件以实验 ID `alpha`、设备 ID `mca` 标识该谱仪。 |

粒子路径为 `source → foil → detector`，信号电缆为 `detector → mca`。`SignalOutput` 的道数为 1024，单位 `count`，时基 `s`，返回区间内各道整数计数。已包含固定几何、每线平均 25 s⁻¹ 的有效探测率、12 keV 标准差高斯响应及 0.006 MeV/道量化；读出端不再乘效率或重复展宽。同一输出可无损分接到第二台 MCA，两台同期逐道计数应相等。

总厚度 `t_um = foil_spec_um × foil_count`；传给共享 `AluminumFoil` 的厚度为 `t_um / 1000 mm`，面密度为 `2.70e-4 × t_um g/cm²`。

| 规格 / µm | 片数 | 总厚度 / µm | 面密度 / g/cm² |
| ---: | ---: | ---: | ---: |
| 1 | 0 | 0 | 0 |
| 1 | 1 | 1 | 0.000270 |
| 1 | 5 | 5 | 0.001350 |
| 2 | 3 | 6 | 0.001620 |
| 2 | 40 | 80 | 0.021600 |

较厚堆叠只会落入完全停止状态，不对 ASTAR 能量表外推。固定几何、法向入射、忽略空气与死层损失的假设未变。空源、空箔、关探测输出、关仪器门必须分别显示：前两项属于装置工况，后两项独立控制时间需求与曝光。

## 可运行入口

从仓库根目录运行：

```text
python -m examples.alpha_equipment
python -m unittest discover -s tests -p test_alpha.py -v
python -m nuclemu run alpha --device mca --enable-output alpha_detector --duration 60 --set foil_spec_um=1 --set foil_count=5 --roi 764:794
```

最小公共调用为：

```python
from nuclemu.catalog import discover
from nuclemu.core import Session
from nuclemu.results import MeasurementView

s = Session(discover()["alpha"], seed=187)
s.configure({"source_present": 1, "foil_spec_um": 1, "foil_count": 5})
s.set_output("alpha_detector", True)
s.start(60, device="mca")
s.advance(60)
product = MeasurementView(s).product()
assert s.instrument("mca").exposure_s == 60
s.set_output("alpha_detector", False)
```

初始输出与门均关闭；`start` 不开启探测输出。示例最后关闭探测输出后，若所有仪器门也关闭，实验室待机。只开探测器时允许时间推进，MCA 不累计曝光；只开 MCA 门时保留实际曝光和合法零计数。关输出不等于移走源。

## GUI 所需换件图清单

以下是交付给装置页的图需求，不表示尚缺的资产已经生成。已有微拟物图片可复用，不必按片数逐张生成。

| 工况 | 图片或状态表现 |
| --- | --- |
| 三峰参考源 | 复用 `rig-source.webp`，保持现有束轴与脚底位置。 |
| 空源座 | 需要空源座图（建议 `rig-source-empty.webp`），保留源座、移去放射源；不能用关电叠层替代。 |
| 1 或 2 µm Al，片数大于 0 | 复用 `rig-foil.webp`，另显示材质、单片规格、片数和派生总厚度。 |
| 空箔架 | 需要空架图（建议 `rig-foil-empty.webp`），保留框架和透射孔；与空源座独立。 |
| 探测输出开/关 | 复用 `rig-silicon.webp`，原位标注独立开关状态，不改变源座或源峰能量。 |
| MCA 门开/关 | 复用 `rig-mca.webp`，显示本实例的门状态与曝光，不连带切探测开关。 |

新空位图应保持原画坐标、可见脚底和输入/输出端口；动画和设备成像不参与抽样。图片只说明装置，不能以图片是否发亮推断一段历史测量的有效曝光。

## 实际 ROI 与峰心

`examples.alpha_equipment` 采用种子 187：启用输出，在同一 **240 s** 的 MCA 门内，于 0、60、120、180 s 分别应用 1 µm/片的 0、5、15、30 片。每个工况段恰为 60 s，期间不增加其他操作；最后关闭探测输出。该连续时间线用于接口复验，不代替仪器主动保存与分轮测量的课堂操作。

无箔两端 ROI 为 845–874、952–982 道，实测峰心分别为 **859.193818416**、**967.472184532** 道，对应 5.155、5.805 MeV。中间峰不参与刻度。

| 片数（规格 1 µm） | 全谱计数 | 中峰 ROI / 道（含两端） | ROI 计数 | 峰心 / 道 | 换算能量 / MeV |
| ---: | ---: | --- | ---: | ---: | ---: |
| 0 | 4536 | 900–929 | 1509 | 914.266401590 | 5.485603244 |
| 5 | 4569 | 764–794 | 1558 | 778.927471117 | 4.673157434 |
| 15 | 4449 | 434–464 | 1500 | 448.978666667 | 2.692459622 |
| 30 | 0 | 全谱 0–1023 | 0 | 无 | 无 |

5 µm 的实测峰移约 **0.812445809 MeV**。这些是统计模型的实际读数，不是独立实验数据或每次测量的标准答案。15 µm 结果低于参考线范围，依赖线性电子学响应假设。程序另输出所有三峰的 ROI、区内计数、峰心和能量，可与仪器上主动保存并导出的 CSV/JSON 原始道谱复算核对；零计数不报告峰心。

## 旧厚度与刻度兼容

新课程只公开规格与片数，厚度为派生量。`Experiment.normalize_settings` 仅在共用 `Session.configure` 设置边界兼容旧命令：

- 旧实时 `foil_um=0` 或 `foil_um=5` 分别明确转成 1 µm 规格的 0 片或 5 片，允许整数 0–40 µm。`Session.set`、CLI 和工作台沿用同一入口。
- 2.5 µm 等不可按默认 1 µm 片精确表示的旧实时输入给出迁移提示，整个设置批次不生效。同批混用 `foil_um` 与任一新箔键时报歧义，即使数值看似一致也不选一方覆盖。
- 旧档读取独立于该转换。档案里的 `foil_um=2.5` 始终是原始总厚度；读回与另存均保持 2.5 µm 和原道谱，片数、规格未知，不补整数片数。
- 实验 ID `alpha`、设备 ID `mca`、1024 道和固定电子学映射不变，旧 `nuclemu.calibration/1` 刻度仍适用。源或箔变化不属于电子学刻度工况；对无峰的谱不据刻度生成不存在的读数。

专项测试实际覆盖空源/空箔四种组合、规格与单位、等厚堆叠、探测与读出门、共享输出、峰移与停止、批量兼容的原子失败、2.5 µm 旧档读回另存及旧刻度。新文件交换入口稳定后，还须用可携整场文件在另一环境复验；本页不声称已完成该跨机验收。
