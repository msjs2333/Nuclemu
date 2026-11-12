# β 射线吸收 · 技术参考

[学生正文](../beta.md) · [教师用书](../teacher/beta.md) · [本册目录](README.md)

## 模型、单位与适用域

固定几何经验总率为 `R = B + source_present × S0 × 2^(−m/H)`，`B=2 s⁻¹`、`S0=100 s⁻¹`、`H=0.112 g/cm²`。`m=2.70 × foil_spec_um × foil_count × 10⁻⁴ g/cm²`，密度2.70 g/cm³；本课50/100 µm每片、0–24片，总厚度0–2.4 mm。`expected_rates(settings)`给出用于抽样的同一有效探测率。

`S0`是已包含固定源窗、接受度和探测效率的净计数率，不是总源活度，不再乘几何效率或另扣空气损失。模型不提供单粒子轨迹、散射角、停点或连续能谱输运。有效半值面密度借用了文献的剂量衰减尺度，并非由该论文直接测得本课计数器响应，详见[模型来源与限制](../model-reference.md#beta)。

新实验`source_present=0`，探测输出开启时仍有环境本底；关闭探测输出由公共层给零输入。物理源发射与电信号开关分开。装置动画只表器材状态，散开源束与空气背景点为视觉元素，与真实计数完全无关，不映射有效率、泊松抽样或单粒子轨迹；绘制不得调用采样或推进曝光。真实本底仍按本课计数模型处理，与画面背景点无关。

## 仪器绑定与窗关系

装置为一台计数器、A/B两窗。兼容ID仍为`counter`、`counter_b`，不是两台实物；分别绑定课程输出`beta_detector`、`beta_detector_b`。当前课程将 A、B 定义为相同装置条件下的两组虚拟重复观测，按同一有效平均响应分别作泊松抽样；给定工况下两组抽样相互独立，包含各自的本底涨落。它们不是同一电缆中同一批真实脉冲的无损分接，更不是把一个真实事件随机计数两次。两组可设不同窗长，共用探测输出启停及整机采集启停。公共框架仍支持真实共享输出的理想无损分接：同一输入只抽样一次再分发，这项公共语义不变。

A设1 s、B设5 s，在共同起点开门5 s后，A有五条完整窗、B一条。2.5 s换箔时不停门，A第3窗和B第1窗包含多段工况。运行修改A窗长，当前窗仍按原长度收完，下一窗采用新长度，B不变。已知确定脉冲的专用测试用于核门边界，随机学生实验不以两路相等或不等作为通过条件。

ORTEC 995资料支持双路独立门控，ST260手册支持每次读数与经过时间。本课学生面板A左B右，大计数下设置单次曝光，整机“开始测量／继续测量”和“暂停测量”同时控制双窗；各列设置单次曝光，右栏另选保存、清空和载入目标。底层独立门是公共接口能力，不能写成当前学生需要逐窗启停。显示及整机控制为教学约定，不冒称任一实物型号具备全部行为。[995资料](https://www.ortec-online.com/-/media/ametekortec/brochures/9/995-a4.pdf) · [ST260手册](https://www.spectrumtechniques.com/wp-content/uploads/ST260-Manual.pdf)

Web整机操作绑定计数器组件的`devices`，以`start_group`、`stop_group`及`configure_group`调用公共原子接口；模式与目标同时设置两窗，保留各列单次曝光。单次曝光输入在各列大计数下方，右栏目标选择仅影响保存、清空、载入。若A已清空或载入、B已有曝光，整机继续从各自已有值接续；不能因整机开始而重置B。

## 原始数据与文件边界

`Snapshot`保存`id`、`device`、`acquisition`、保存时物理时刻`time_s`、实际截止曝光`exposure_s`、累计`counts`、按工况分段`segments`和逐窗`windows`。`time_s`不等于曝光，累计段不能代替逐窗整数读数。载入来源另由`source`保留。跨文件项目用UUID，内核短整数编号不能充当全局身份。

每个`InstrumentWindow`有`device`、`number`、`acquisition`、`start_exposure_s`、`end_exposure_s`、`counts`、`parts`、`complete`。起止为本轮累计曝光坐标；相减得到本窗曝光，不能直接当实验室物理起止时刻。`parts`保留构成窗的测量段及工况变化，`complete`区分完整预设统计窗与部分统计窗，不表示数据是否有效或可读。`session.instrument_windows(device)`读取当前窗明细，`snapshot.windows`固定保存时的值。窗中途保存、手停或定时先到限时末窗可为`complete=False`，实际曝光和计数仍有效；保存不强行补满统计窗或抽样。续采同窗到原完整窗末时更新该行，旧快照不变。

“保存”留存原始数据；记录页“导入”只加缓存；仪器“载入测量数据”才恢复目标当前数据并可续采。`.nuclemu`保留已留存快照、轮次和设置历史，未保存轮次只留元数据。逐窗序列必须经缓存、JSON/CSV和整场重开逐行核对，不能用仅一行累计值冒充可恢复的五窗数据。[文件交换](../exchange.md) · [公共采集语义](../measurement-workflow.md)

旧整场文件若声明两窗共享同一个输出，重开及续采保留其历史共享输入模型；新课程的分别取样约定不重写旧记录或历史模型。单项旧记录载入当前课程时，只把已存计数与曝光作为固定前缀，新增曝光按当前两组分别取样的模式采集；旧前缀不重新抽样，也不能据此宣称整份累计数据都是独立重复观测。

旧档缺逐窗明细时只保留已知累计前缀`window_prefix`的曝光与计数，不能拆造过去的窗。新窗接着前缀曝光累计。跨场载入时，旧`parts`的物理坐标与`origin`来源不改写为本场时刻；本场可以从0 s、已有3 s曝光起继续测量。载入只替换目标数据，不自动换源、换箔或改另一窗。

## 本底分析的适用条件

学生工作台仅测量和导出；本底处理在本地完成。CLI或公共分析函数接受显式参考时，用记录身份、源状态、设备及曝光核适用性。`results.net_count_rate(Ns, ts, Nb, tb)`只接收四个标量，不能替调用层校验来源或时间重叠。

独立样品与本底可用泊松代入近似。本课 A、B 给定工况下分别抽样；同一组同轮重叠累计快照、载入旧记录后共享的前缀仍不独立，不能因分属A/B或文件不同就消除既有数据重叠。公共框架实际共享输入的重叠窗也不满足独立假设。低计数负净率正常保留；近似标准不确定度不是精确置信区间。更换本底只改引用和派生量，不改原始计数或随机流。

## 复验入口

### 一行填写示例的复验

下面时间线取得60 s本底与20 s样品，显式装源以免依赖默认值。整数计数以当前课程模型实际输出为准，不沿用旧抽样方式的固定基线。分别保存后，使用公共文件接口导出并重开：

```python
from nuclemu.catalog import discover
from nuclemu.core import Session
from nuclemu.exchange import capture_session, save_package, load_package, export_item, load_item

s = Session(discover()["beta"], seed=42)
s.set_output("beta_detector", True)
group = ("counter", "counter_b")
s.configure_group(group, duration_s=60, count_limit=None)
s.start_group(group)
s.advance(60)
background = s.snapshot("counter")
for device in group:
    s.clear(device=device)
s.configure({"source_present": 1, "foil_spec_um": 100, "foil_count": 4})
s.configure_group(group, duration_s=20, count_limit=None)
s.start_group(group)
s.advance(20)
sample = s.snapshot("counter")
doc = capture_session(s)
save_package("beta-example.nuclemu", doc)
loaded = load_package("beta-example.nuclemu")
assert loaded == doc
for item in loaded["items"]:
    for format in ("json", "csv"):
        bundle = load_item(export_item(loaded, item["id"], format))
print(background.counts, background.exposure_s, len(background.windows))
print(sample.counts, sample.exposure_s, len(sample.windows))
```

本例使用内核受控时间推进，文件结果不代替浏览器按钮验收。

### 专项与边界

```text
python -m examples.beta_windows
python -m examples.beta_background
python -m unittest discover -s tests -p "test_beta*.py" -v
```

[β器材与采集](../beta-acquisition.md)维护最新可运行调用、字段与文件例。复验记录实验、种子、参数、各操作物理时刻、目标窗、实际曝光与逐窗计数。比较GUI/CLI须使用同一时间线；只相同种子不足以保证不同操作流程逐次相同。

文件验收至少走一次三窗保存、分别导出JSON/CSV、载回目标、续采一窗得到四行；非空目标取消或无效文件保持原值，另一窗不受影响。另走1 s/5 s、跨工况和未保存轮次重开。课程专项不替代最终页面及文件链路走读。
