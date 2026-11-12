# β 课程的共用探测输入与双窗核验

本文核验 β 课程定义和 Python 公共调用。学生手册见 [β 射线吸收](beta.md)，采集、缓存和文件的交付约定以[测量工作流](measurement-workflow.md)为准。GUI 和 CLI 由各自入口接入同一课程，不在课程内实现另一套时钟或采集器。

## 器材与接口

| 对象 | 标识与默认值 | 作用 |
|---|---|---|
| 源座 | `source`；`source_present=1` | 0 为空源座，1 为 β 源。空源座仍有环境本底，独立于空箔和探测开关。 |
| Al 箔架 | `foil`；`foil_count=0`，`foil_spec_um=100` | 0–24 片；单片可选 50/100 µm，属于本课程的教学选定规格。0 片为空箔。 |
| 探测器 | `detector`，`output="beta_detector"` | 输出含源窗、固定几何、阈值与探测效率及环境本底的有效计数，不再重复乘效率。 |
| 计数器 A | `counter`，`input="beta_detector"` | 保留原设备 ID，单通道整数计数；独立开关采集门。 |
| 计数器 B | `counter_b`，同一输入 | 理想无损分接同一批计数；不是另抽一次泊松数。 |

总厚度 `foil_spec_um × foil_count`，单位 µm。用 `AluminumFoil(总厚度 / 1000)` 换成 mm 后得到面密度。例如 50 µm 的 2 片与 100 µm 的 1 片均为 0.10 mm、0.027 g/cm²；24 片默认规格为 2.4 mm、0.648 g/cm²，未扩展原有效吸收模型的总厚度范围。两种规格不代表某套实物器材的标称值。

新课程保留 `beta`、`source_present`、`foil_count`、`counter`。`sample_counts` 返回的是具名探测输出 `beta_detector`，模型按给定区间抽样一次；框架再向每台开门的设备分发。部件绑定输出、设备绑定输入，界面不根据部件文字猜测端口。已有文件仍按自身设备和数值设置读回；缺少 `foil_spec_um` 的既有 β 记录按原课程的 100 µm/片解释，不回写旧数据，也不补造第二台仪器的读数。

初始探测输出及两台采集门均关闭。需要测源信号或空源本底时先 `set_output("beta_detector", True)`；空源本底的期望率为 2 s⁻¹。关闭探测输出后，已开门的仪器仍有曝光，但输入为合法零计数。全部输出和门都停止后，物理时间待机。

## 两个 5 s 窗与一个 10 s 窗

在仓库根目录执行：

```text
python -m examples.beta_windows
```

其中 `dual_windows()` 的完整操作线如下。规格为 100 µm、4 片，种子为 42：

```python
from nuclemu.core import Session
from nuclemu.experiments.beta import EXPERIMENT

s = Session(EXPERIMENT, seed=42)
s.set("foil_count", 4)
s.set_output("beta_detector", True)
s.start(5, device="counter")
s.start(10, device="counter_b")
s.advance(5)
first = s.snapshot("counter")          # 279 次，5 s；保存后读数仍保留
assert s.instrument("counter_b").running
s.clear(device="counter")            # 已显式保存第一窗；只清 A 的当前读数
s.start(5, device="counter")
s.advance(5)
second = s.snapshot("counter")         # 271 次，5 s
long = s.snapshot("counter_b")         # 550 次，10 s
assert first.counts[0] + second.counts[0] == long.counts[0]
s.set_output("beta_detector", False)
```

A 首次到限时 B 已读到同一段 279 次并继续运行。A 清空后再开始建立新轮次，原第一窗快照仍保留。`dual_windows(reopen=False)` 不再开启 A，结果为 A 保持 279 次/5 s、B 继续到 550 次/10 s。操作期间不推进墙钟等待之外的物理时间；另一台设备不会因 A 停门而暂停。

若要同一轮累计到 10 s，可提高 A 的累计曝光目标后继续；若要保留两份独立 5 s 窗，按上例保存、清空再开始。不能把两份重叠的累计快照当作独立测量相加。A 与 B 的同期窗共享计数，作差时也不能套用相互独立的泊松方差相加。

同一完整时间线下，改变刷新次数或推进批次应得到相同读数。当前区间模型没有脉冲到达时刻；改变某台仪器的窗内关门时刻会改变区间划分，不能据此承诺不同操作线仍复现同一潜在事件流。

CLI 的单窗对照可直接运行以下命令；把 `counter` 改成 `counter_b` 可单独核对 B，同一配置均得 550 次、10 s：

```text
python -m nuclemu run beta --seed 42 --device counter --enable-output beta_detector --set foil_count=4 --set foil_spec_um=100 --duration 10
```

原 `--device counter` 仍指 A；现在有两台计数器，选择设备时使用具体实例 ID。未启用输出时，开门曝光仍有效、计数为零，命令会显示输出关闭。CLI 每个 `--step` 表示独立测点，下一步前会清空所选仪器的当前轮；本次运行的窗口产品仍保留各测点，供直接 CSV/JSON 输出，不等同于整场快照档案。以下命令得到 A 的 279 和 271 次，可与 B 单 10 s 的 550 次核对：

```text
python -m nuclemu run beta --seed 42 --device counter --enable-output beta_detector --set foil_count=4 --step 5 --step 5
```

同场共享输入、按键保存和清空的完整操作线仍以本页 Python 样例为复核入口；直接调用 `Session.start()` 不会自动清空。Web 双门操作由图形入口接入。

## 不同曝光与独立本底

同一脚本的 `background_comparison()` 只使用 A，依次采集并显式保存、清空三个测点。探测输出始终打开，种子 42：

| 测点 | 源座 | 100 µm 箔片数 | 实际曝光 / s | 原始计数 |
|---|---|---:|---:|---:|
| 本底 1 | 空 | 0 | 19.5 | 32 |
| 样品 | 有源 | 4 | 7.25 | 399 |
| 本底 2 | 空 | 0 | 9.25 | 20 |

选择本底 1 时，样品净率为 **53.393457 ± 2.770400 s⁻¹**；改选本底 2 后为 **52.872321 ± 2.797268 s⁻¹**。两次样品原始读数均为 399 次、7.25 s，全部原始段和已保存快照不变，只改变分析引用。净率使用样品与参考各自的曝光计算；空源本底与样品须独立且适用。净率可以为负，合法零计数照常保存。

此处的完整 `MeasurementView` 产品用来诊断原始曝光窗。学生保存和交换文件应依据主动保存的快照，不能因为查看、导出整场或保留内存诊断记录而补存未保存的读数。

## 专项检查

```text
python -m unittest discover -s tests -p "test_beta*.py" -v
```

检查涵盖旧有效吸收曲线的均值与方差、源座和箔架独立、规格换算及等厚片组、同一输入逐窗一致、5+5=10、A 停 B 继续、探测关闭期间保留曝光与零输入、不同曝光本底及换参考不改原数、按设备导出的实际曝光、旧单计数器 SQLite 档原样读回，以及相同操作线下刷新/推进分块不改变计数。GUI 和 CLI 应使用本页相同的设备、种子、参数和物理时刻复验，不只比较期望曲线。
