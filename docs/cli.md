# 命令行实验

在仓库根目录执行 `python -m nuclemu`。安装项目后，`nuclemu` console script 调用相同的 `nuclemu.cli:main`。以下命令适用于 PowerShell；时间单位统一为秒，采集按模拟物理时间立即完成，无需等待同样长的墙钟时间。

```powershell
python -m nuclemu --help
python -m nuclemu list
python -m nuclemu list alpha
python -m nuclemu validate
python -m nuclemu gui
```

`list` 给出实验 ID、测量问题、操作指引、参数键、单位、默认值、范围、整数要求及设备 `kind:id` 和道数。装置部件列出用途、所控制的参数和绑定的设备实例；连接区分粒子路径 `particle` 与电信号 `signal`。例如 `alpha` 的铝箔架绑定 `foil_um`，硅探测器和多道谱仪都指向 `spectrum:mca`；`beta` 的源座绑定 `source_present`，箔架绑定 `foil_count`。`list alpha` 只显示该实验的详情。

`list` 与浏览器目录共用 `catalog.describe(experiment)`，查看资料不建立 Session、不采样。没有显式装置定义的本地模块仍可加载：目录用设备生成仪器部件，并将参数集中列在控制部件中。`validate` 加载并检查实验定义，不运行物理测量。

`gui` 惰性调用 `launch(paths=...)`，默认启动本机 Web 服务并打开默认浏览器中的实验工作台。额外模块目录照常传给工作台；停止服务使用启动命令所在终端的 `Ctrl+C`。`list`、`validate` 和 `run` 不启动 Web 服务或浏览器，不需要图形窗口。

额外实验目录通过重复 `--path DIRECTORY` 指定，可放在子命令前或后。目录内非下划线开头的 `.py` 文件须导出公共 `Experiment` 类型的 `EXPERIMENT`。模块会执行 Python 代码，只加载自己信任的目录。重复实验 ID、无效定义及目录不存在均报错。

```powershell
python -m nuclemu list --path D:\MyLabs
python -m nuclemu gui --path D:\MyLabs
```

## 设置和多段采集

`run EXPERIMENT --duration SECONDS` 打开一次定时采集门。`--set KEY=VALUE` 可重复，使用 `list` 显示的参数单位，不接受带单位的数值字符串。`--seed` 默认为 0。

重复 `--step "SECONDS,KEY=VALUE,..."` 可在同一 Session 中连续采集多个工况，与 `--duration` 二选一。每段先设置参数，再开门；时间到后自动关门。未指定的参数沿用上一段，第一段沿用实验默认值和 `--set` 的初值。即使相邻两段设置相同，也保留两次独立采集。当前没有计数限停或脚本内手动停门；图形界面的手动开关门对应公共 `Session.start()`、`advance()`、`stop()`。

默认摘要显示每段起止时间、曝光、设置、各设备累计计数和计数率。`--device KIND:ID` 选择设备；也可用精确实例 ID 或唯一 kind。实例 ID 优先于其他设备的同名 kind；多个同类设备用 `kind:id` 区分。

```powershell
python -m nuclemu run beta --duration 2.5 --set foil_count=4 --seed 42
python -m nuclemu run beta --step 1 --step 1 --device counter:counter
```

## β 本底与样品

下面在同一 Session 中先采 1.25 s 本底，再采 4 片铝箔的 2.5 s 有源计数。`--background 1` 用第 1 段对其余段的计数器计算净率及独立泊松标准不确定度；编号从 1 开始，各段分别使用实际曝光，允许负净率。

```powershell
python -m nuclemu run beta --seed 42 --device counter:counter --step "1.25,source_present=0" --step "2.5,source_present=1,foil_count=4" --background 1 --output beta.json --output beta.csv
```

当前模型和种子下，两段计数为 1、122，净率约为 `48 +/- 4.48999 1/s`。短曝光用于重现验收，课堂测量建议增加曝光以减小涨落；同一本底用于多个样品时，净率之间存在共享本底引入的相关性。

## α 参考谱、加箔谱与刻度

```powershell
python -m nuclemu run alpha --seed 187 --device spectrum:mca --step "2.25,foil_um=0" --step "1.25,foil_um=5" --roi 845:875 --output alpha.json --output alpha.csv
```

两段分别累计 172、92 个计数，曝光分别为 2.25、1.25 s。`--roi FIRST:LAST` 使用含两端的道号，输出 ROI 总计数和计数加权峰心；空 ROI 显示 `None`。该参数要求选择一台 spectrum 设备。一个 ROI 会用于所有段，因此分析能损时须在每段中选择同一条谱线的新位置；固定窗口可能包含加箔后的另一条谱线。

例如先运行以上命令，再在 Python 中使用导出的参考谱测得两点刻度，并在加箔谱跟踪最低能谱线：

```python
import json
from nuclemu.results import Calibration, roi_centroid

with open("alpha.json", encoding="utf-8") as stream:
    product = json.load(stream)
reference, foil = [s["readings"]["mca"] for s in product["segments"]]
c1 = roi_centroid(reference, 845, 875)
c2 = roi_centroid(reference, 950, 985)
if c1 is None or c2 is None:
    raise ValueError("Reference peaks require more exposure")
calibration = Calibration("alpha", "mca", 1024, c1, 5.155, c2, 5.805)
calibration.save("alpha-calibration.json")
shifted = roi_centroid(foil, 700, 735)
if shifted is not None:
    print("Energy loss / MeV:", calibration.energy(c1) - calibration.energy(shifted))
```

载入刻度后可再次运行相同采集计划。相同种子和调用计划产生相同计数；加载刻度、显示摘要和导出不会消耗随机数。

```powershell
python -m nuclemu run alpha --seed 187 --step "2.25,foil_um=0" --step "1.25,foil_um=5" --device spectrum:mca --roi 845:875 --calibration alpha-calibration.json --output alpha-calibrated.csv
```

刻度绑定实验 ID、设备实例和道数，以 MeV 保存。设备不匹配时明确报错。更改箔厚继续使用既有刻度，不能把透射峰重新指定为无箔能量。物理依据、模型范围和推荐选峰方法见 [α 实验](alpha.md)；β 模型及统计说明见 [β 实验](beta.md)。

## 产品与 GUI 对齐

`--output` 可重复，扩展名必须为 `.csv` 或 `.json`，目标父目录须已存在。输出不得指向 `--calibration` 的输入文件，包括相对路径和文件链接别名；发现冲突时，在采集、摘要和任何文件写出之前报错。默认导出全部设备；指定 `--device` 后只导出该设备。JSON 保留完整各段设置、整数计数、设备描述、种子和曝光边界；CSV 每段每道一行，包含设置、曝光及计数，载入刻度后另含 `energy_MeV`。摘要中的 ROI 和净率为派生读数，产品仍保存原始累计计数，供后续重新分析。

CLI 与浏览器工作台共用 `discover(paths)`、`catalog.describe(experiment)`、`Experiment.parameters/devices`、`Session` 和 `MeasurementView(session).product()`。装置中看到的参数键对应 CLI 的 `--set` 或 `--step`，部件绑定的仪器实例对应 `--device KIND:ID`。对齐时使用相同实验、种子、设备实例、参数变化顺序及每次开关门时刻；界面刷新可以拆分 `advance()`，不改变采集窗。CLI 每个 step 对应工作台一次定时采集；工作台的刷新、ROI、刻度和导出同样只消费现有产品。以相同产品的整数计数和曝光比较，避免把随机读数与模型期望率直接当作相等性条件。

运行入口验收：

```powershell
python -m unittest discover -s tests -p "test_cli*.py" -v
```
