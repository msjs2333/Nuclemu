# α 粒子在铝箔中的能量损失 · 技术参考

操作与空表见[学生用书](../alpha.md)，课堂检查与已填表见[教师用书](../teacher/alpha.md)，[本册目录](README.md)连接公共接口。本页连接课程实现和复验依据，详细常数与接口不另复制一套。

| 维护任务 | 权威内容 |
|---|---|
| 参数、绑定、独立输出、旧配置兼容 | [器材与接口](../alpha-equipment.md)；[`experiments/alpha.py`](../../nuclemu/experiments/alpha.py)。 |
| ASTAR、单位、插值、电子学响应及公开资料 | [模型参考 α 节](../model-reference.md#alpha)。 |
| 原始谱、ROI、峰心、两点刻度 | [`examples.alpha_equipment`](../../examples/alpha_equipment.py)与[教师填写示例](../teacher/alpha.md#可复验的填写示例)。 |
| 门、轮次、主动保存与文件语义 | [测量工作流](../measurement-workflow.md)与[架构](../architecture.md)。 |

## 课程边界与数据流

源座使用 `source_present`；箔架使用 `foil_spec_um`、`foil_count`。总厚度先以 µm 相乘，再除以 1000 转为材料接口的 mm。允许规格 1、2 µm/片，片数 0–40；最大厚度使用射程截止，不向表外能量外推。

硅探测器组件绑定输出 `alpha_detector`，谱仪组件绑定设备 `mca`，设备输入连接该输出。新实验默认空源，已有文件保留源末态。探测输出和谱仪门独立；关闭输出只使新增计数为零，不清除已有计数，开门曝光继续。空源、空箔、输出关闭及未采集不能互相替代。本课不含本底，空谱不能证明真实装置本底为零。

模型在所列 0–6 MeV 范围内使用纯铝 CSDA 射程表和固定电子学响应。忽略散射、能损涨落、空气/死层、死时间与本底；给定厚度确定是否停止，不据此模拟真实透射概率。

装置动画按当前器材状态作视觉示意，散开的源束和少量空气背景点与测量抽样完全分离。点数、运动、疏密及角度均不是模型输出的轨迹、能量或计数，不把背景点转为α本底输入；绘制与开关不得调用采样或推进曝光。

谱课按区间保存道谱，不为无关的先后关系保留每个脉冲。共同输入只采样一次，再分给开启的仪器。复现需要种子、设置与完整操作时间线；仅相同种子不足以保证不同采集流程逐道相同。

## 设置与历史档

实时旧键 `foil_um` 在共享设置边界归一：整数 0–40 µm 转成 1 µm/片及对应片数。与新箔键混批或不支持的厚度明确报错，整批不部分生效。历史文件不经过实时迁移；原档 2.5 µm 保持原值，不补造片数，不改原始谱、曝光与刻度。

已保存记录保持截止曝光，后续采集不改写它。逐道核对使用已保存谱的 CSV/JSON 导出。缺失设备或未主动保存的谱不是零计数测量，也不能由模型补生成历史读数。

谱文件保留全部1024道（含零计数道），曝光以s、能量刻度以MeV记录。ROI包含两端道号，重心为区内计数加权道址，空ROI返回无重心。Web中“计算 ROI 重心”手动分析一次，冻结所选谱或其不可变引用、ROI道界、截止曝光、当时刻度、区内计数、重心及适用能量。读状态或继续采集不重算；修改选谱、选区或刻度也不覆盖上次分析，主动重算才更新。谱图固定全道0–1023，能量轴只映射全道两端。`state.roi_result`是本会话的显式分析结果，刷新保留；`state.readout`只提供实时总量。计算不调用保存，实验文件不恢复旧结果数字；学生须显式保存原谱，重开后重新计算。刻度需匹配实验、设备、道数与适用响应设置；换箔不改变电子学响应，可继续使用原刻度。保存刻度时，兼容且尚未关联刻度的已保存谱可关联本次刻度，已有刻度关联保留；道计数和截止曝光不变。已保存谱使用自身关联刻度；从历史谱开始新采集时应恢复本场当前刻度，不能继承历史显示态。普通保存与“保存并清空”应关联同一份适用刻度。

跨工况快照的累计道谱保留整体计数与曝光，分段之和应逐道等于整谱；重开后两种视角均可查看。查看参考谱、导入记录、载入刻度和恢复当前测量有各自范围，操作失败或取消不能改写原始值。[文件接口](../exchange.md)

## 复验与交付边界

### 单一工况保存与填写复验

以下以两次独立清空后的60 s轮次采集无箔与5 µm谱，显式装源。种子187下中峰ROI分别取900–929、764–794道，峰心914.266402、778.927471道，按实测两点刻度得能损0.812446 MeV。两张谱各自曝光60 s，不能用整场120 s代填。

```python
from nuclemu.catalog import discover
from nuclemu.core import Session
from nuclemu.results import Calibration, roi_centroid
from nuclemu.exchange import (capture_session, cache_calibration, bind_calibration,
    save_package, load_package, export_item, load_item)

s = Session(discover()["alpha"], seed=187)
s.configure({"source_present": 1, "foil_spec_um": 1, "foil_count": 0})
s.set_output("alpha_detector", True)
s.start(60, device="mca")
s.advance(60)
reference = s.snapshot("mca")
cal = Calibration("alpha", "mca", 1024,
    roi_centroid(reference.counts, 845, 874), 5.155,
    roi_centroid(reference.counts, 952, 982), 5.805)
s.clear(device="mca")
s.set("foil_count", 5)
s.start(60, device="mca")
s.advance(60)
sample = s.snapshot("mca")
doc = capture_session(s)
measurements = [item["id"] for item in doc["items"]]
cid = cache_calibration(doc, cal)
for identity in measurements:
    bind_calibration(doc, identity, cid)
save_package("alpha-example.nuclemu", doc)
loaded = load_package("alpha-example.nuclemu")
assert loaded == doc
for format in ("json", "csv"):
    bundle = load_item(export_item(loaded, measurements[0], format))
```

### 课程专项

在仓库根目录运行：

```text
python -m examples.alpha_equipment
python -m unittest discover -s tests -p "test_alpha.py" -v
```

专项覆盖规格与单位、等厚谱、空源/空箔、门与输出、共享谱、峰移与停止、旧实时设置原子失败及历史档/刻度保留。教师表取连续 240 s 时间线中的各 60 s 工况段，不冒充学生主动保存文件包。

最终按钮、内置阅读、跨文件身份和异环境重开由公共 GUI/文件层联调后验收；课程专项通过不代表这些功能已完成。
