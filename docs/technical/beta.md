# β 射线吸收 · 技术参考

本页是 β 技术册入口。学生操作与空表见[学生正文](../beta.md)，教学讨论和实测填写示例见[教师用书](../teacher/beta.md)。三者共用一份课程，不复制多套模型或答案。

| 维护任务 | 权威内容 |
|---|---|
| 参数、设备、端口、独立开关及旧档兼容 | [β 器材与接口](../beta-acquisition.md#器材与接口)；实现为 [`experiments/beta.py`](../../nuclemu/experiments/beta.py)。 |
| 同源双窗、A 停 B 继续、不同推进批次 | [双窗公开调用](../beta-acquisition.md#两个-5-s-窗与一个-10-s-窗)；可运行 [`examples.beta_windows`](../../examples/beta_windows.py)。 |
| 模型方程、单位、教学参数、公开资料及适用域 | [模型参考 β 节](../model-reference.md#beta)。 |
| 窗、轮次、主动保存与文件口径 | [合并的测量工作流](../measurement-workflow.md)与[公共架构](../architecture.md)。 |
| 独立本底、低计数负率、相关窗边界 | [教师讨论](../teacher/beta.md#哪些记录不能当作独立观测)与 [`examples.beta_background`](../../examples/beta_background.py)。 |

## 07β 分析输入和输出

分析使用已保存的测量身份、设备、原始整数计数和截止曝光。源条件由课程的 `Device.background_conditions` 声明；本课程空源为 `source_present=0`。探测输出关闭的零输入段不能仅凭计数为零就识别为环境本底。

在样品与参考适用且独立时，复用 `results.net_count_rate(Ns, ts, Nb, tb)`。更换参考只替换引用和派生的净率/近似标准不确定度，不改变样品、原始窗、快照或随机源。没有参考时保留总率；参考缺失时显示缺依据；同一记录自身显示参考，不做独立自扣。

共同输入的重叠曝光和同轮重叠累计快照不满足独立公式的假设。本课样例明确给出有效与无效配对；数值函数本身只收到四个标量，不能从它们推断来源或重叠。GUI/档案层仍需保留来源及窗口信息，不把该函数当作身份校验器。当前补充样例不新增相关计数求解器。

现行 `Snapshot` 以 `device`、`acquisition`、`id`、`time_s`、`exposure_s`、`counts` 及分段 `segments` 描述可读快照；其中 `time_s` 是保存时实验室时刻，`exposure_s` 是快照实际截止曝光，两者不必相等。跨文件的持久标识与导入映射由公共文件层定义，不能直接把本地短整数 ID 当成全局身份。原始 `MeasurementView` 的 `readings` 是按设备稀疏保存的，缺失设备不是零计数测量。

## 复验和版本边界

在仓库根目录运行：

```text
python -m examples.beta_windows
python -m examples.beta_background
python -m unittest discover -s tests -p "test_beta*.py" -v
```

第一项复验同场双窗与不等曝光，第二项直接复用第一项的数据，补真实零计数负率、可配对的非重叠时间窗，以及已知共享/重叠记录为什么不能当独立本底。所有数字都注明种子和完整操作线；并行采集改变区间划分后，不承诺不同操作线保留同一随机样本。

CLI 的窗口产品 JSON/CSV 与仪器主动保存的快照、整场存档是不同交付层。不能用诊断原始窗冒充已经主动保存的记录，也不能承诺尚未接好的 Web 本底面板或跨文件来源映射已完成。最终三册的按钮步骤、包字段与内置阅读入口由两端联调后核实。
