# 命令行实验

在仓库根目录执行 `python -m nuclemu`。安装项目后，`nuclemu` console script 调用相同的 `nuclemu.cli:main`。以下命令适用于 PowerShell；时间单位统一为秒，采集按模拟物理时间立即完成，无需等待同样长的墙钟时间。

```powershell
python -m nuclemu --help
python -m nuclemu list
python -m nuclemu list alpha
python -m nuclemu validate
python -m nuclemu gui
```

`list` 给出实验 ID、测量问题、操作指引、参数键、单位、默认值、范围、整数要求及设备 `kind:id` 和道数。装置部件列出用途、所控制的参数和绑定的设备实例；连接区分粒子路径 `particle` 与电信号 `signal`。两课的箔架都用单片规格 `foil_spec_um` 和片数 `foil_count` 设置，总厚度由两者相乘得到；源座与探测输出另行控制。仪器输入绑定探测输出，`--device` 使用读出仪器的实例 ID。`list alpha` 只显示该实验的详情。

`list` 与浏览器目录共用 `catalog.describe(experiment)`，查看资料不建立 Session、不采样。没有显式装置定义的本地模块仍可加载：目录用设备生成仪器部件，并将参数集中列在控制部件中。`validate` 加载并检查实验定义，不运行物理测量。

`gui` 惰性调用 `launch(paths=...)`，默认启动本机 Web 服务并打开默认浏览器中的实验工作台。额外模块目录照常传给工作台；停止服务使用启动命令所在终端的 `Ctrl+C`。`list`、`validate` 和 `run` 不启动 Web 服务或浏览器，不需要图形窗口。

额外实验目录通过重复 `--path DIRECTORY` 指定，可放在子命令前或后。目录内非下划线开头的 `.py` 文件须导出公共 `Experiment` 类型的 `EXPERIMENT`。模块会执行 Python 代码，只加载自己信任的目录。重复实验 ID、无效定义及目录不存在均报错。

```powershell
python -m nuclemu list --path D:\MyLabs
python -m nuclemu gui --path D:\MyLabs
```

## 设置和多段采集

`run EXPERIMENT --duration SECONDS` 打开一次定时采集门。`--set KEY=VALUE` 可重复，使用 `list` 显示的参数单位，不接受带单位的数值字符串。`--seed` 默认为 0。

重复 `--step "SECONDS,KEY=VALUE,..."` 可在同一 Session 中连续采集多个工况，与 `--duration` 二选一。每个 step 是独立测点：前一步定时结束后，入口清空目标仪器，再设置参数并开启新轮；此前各点仍保留在本次命令的测量产品中。未指定的参数沿用上一段，第一段沿用实验默认值和 `--set` 的初值。即使相邻两段设置相同，也保留两次独立采集。普通 `Session.stop(device=...)` 暂停后再 `start(device=...)` 继续的是同一轮，本身不清空；CLI 多 step 不表示这种续采。当前没有计数限停或脚本内手动停门。

默认摘要显示每段起止时间、曝光、设置、各设备累计计数和计数率。`--device KIND:ID` 选择设备；也可用精确实例 ID 或唯一 kind。实例 ID 优先于其他设备的同名 kind；多个同类设备用 `kind:id` 区分。

```powershell
python -m nuclemu run beta --set source_present=1 --duration 2.5 --set foil_spec_um=100 --set foil_count=4 --seed 42 --device counter:counter --enable-output beta_detector
python -m nuclemu run beta --step 1 --step 1 --device counter:counter --enable-output beta_detector
```

### 具名探测输出与独立采集门

声明了 `SignalOutput` 的课程将探测输出和读出仪器分开控制。`list` 显示输出 ID、计数和时间单位，以及仪器的 `input` 绑定。`--enable-output ID` 可重复，在第一段采集前开启指定输出，并在本次调用的各段间保持开启；未列出的输出保持关闭。关闭探测输出仍可开门，得到有实际曝光的零计数，摘要明确显示 `off (zero input)`。

对这类课程，`--device` 同时选择实际开门、摘要和导出的仪器；未指定时所有仪器开相同的定时门。各段只显示实际存在的设备读数。`--background` 要先用 `--device` 定位一台仪器，段编号按该仪器本次调用的采集顺序从 1 开始。未声明独立输出的课程仍按原有共享采集方式运行，`--device` 只选择读数和导出。

```powershell
python -m nuclemu list split-signal --path examples/courses
python -m nuclemu run split-signal --path examples/courses --seed 187 --device counter:a --enable-output detector --duration 10
python -m nuclemu run split-signal --path examples/courses --seed 187 --duration 1
```

第二条对 A 实际开门 10 s，探测器全程开启；第三条探测器保持关闭，A/B 均有 1 s 曝光和零计数。CLI 当前只提供整次调用的初始输出开关及逐段参数设置，不提供中途切换输出或不同仪器的复杂开关脚本。核对第 3–7 s 关闭探测器的双仪器时间线可运行 `python -m examples.split_signal`，或直接使用公共 `Session.set_output()`、`start(..., device=...)`、`stop(device=...)`。两端比较必须使用同一完整物理操作时间线。

## β 本底与样品

下面在同一 Session 中先采 1.25 s 本底，再采 4 片铝箔的 2.5 s 有源计数。`--background 1` 用第 1 个独立测点对其余段的计数器计算净率及独立泊松标准不确定度；编号从 1 开始，各段分别使用实际曝光，允许负净率。

```powershell
python -m nuclemu run beta --seed 42 --device counter:counter --enable-output beta_detector --set foil_spec_um=100 --step "1.25,source_present=0" --step "2.5,source_present=1,foil_count=4" --background 1 --output beta.json --output beta.csv
```

当前独立重复观测模型和种子下，上述命令的两段计数为 61、3774，净率约为 `1460.8 +/- 25.3551 1/s`。短曝光用于重现验收；当前课程建议先测 30 s 本底，再对各厚度测 5 s 有源计数。同一本底用于多个样品时，净率之间存在共享本底引入的相关性。历史文件的已有观测保持原数，旧整场继续使用其已识别的响应模型。

## α 参考谱、加箔谱与刻度

```powershell
python -m nuclemu run alpha --set source_present=1 --seed 187 --device spectrum:mca --enable-output alpha_detector --step "2.25,foil_spec_um=1,foil_count=0" --step "1.25,foil_spec_um=1,foil_count=5" --roi 845:875 --output alpha.json --output alpha.csv
```

在种子 187、探测输出全程开启、两个独立轮次的上述操作下，两段分别累计 172、86 个计数，曝光分别为 2.25、1.25 s。统计窗从各轮的有效曝光起点划分；这是当前独立轮次语义的基线，已有文件中的观测计数仍按原数据读取。相同完整操作时间线下，旧厚度键与新规格/片数逐道相等。`--roi FIRST:LAST` 使用含两端的道号，输出 ROI 总计数和计数加权峰心；空 ROI 显示 `None`。该参数要求选择一台 spectrum 设备。一个 ROI 会用于所有段，因此分析能损时须在每段中选择同一条谱线的新位置；固定窗口可能包含加箔后的另一条谱线。

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
python -m nuclemu run alpha --set source_present=1 --seed 187 --step "2.25,foil_spec_um=1,foil_count=0" --step "1.25,foil_spec_um=1,foil_count=5" --enable-output alpha_detector --device spectrum:mca --roi 845:875 --calibration alpha-calibration.json --output alpha-calibrated.csv
```

刻度绑定实验 ID、设备实例和道数，以 MeV 保存。设备不匹配时明确报错。更改箔厚继续使用既有刻度，不能把透射峰重新指定为无箔能量。物理依据、模型范围和推荐选峰方法见 [α 实验](alpha.md)；β 模型及统计说明见 [β 实验](beta.md)。

旧命令的 α `foil_um=0`、`foil_um=5` 等整数总厚度仍可使用，共用设置入口将其转换为 `foil_spec_um=1` 和对应片数。不能用默认 1 µm 片精确表示的实时输入，例如 `foil_um=2.5`，会报迁移提示并保持原有效状态；同一组 `--set` 或同一个 `--step` 内不能混用 `foil_um` 与 `foil_spec_um`/`foil_count`。不同 step 是不同设置批次。旧档案和刻度中的 `foil_um` 始终表示原始总厚度：2.5 µm 保留 2.5 µm、片数未知，不能经实时设置转换来读回。

## 产品与 GUI 对齐

`run --package FILE.nuclemu` 在每个完成的 step 明确缓存一份快照，并将这些测点、轮次及配置写为可携整场文件。它与 `--output` 的普通测量 CSV/JSON 可以同时使用，但目标文件必须不同；指定 `--background` 时也保存本底和样品的缓存 UUID 引用，重开后可用原始计数和实际曝光复算净率；载入的刻度也作为已保存项目带入包内，并关联到适用测量。整场文件是含版本清单和 SQLite 的 `.nuclemu` 压缩包，可离线复制到另一目录或电脑。

```powershell
python -m nuclemu run alpha --set source_present=1 --seed 187 --device mca --enable-output alpha_detector --step "2.25,foil_spec_um=1,foil_count=0" --step "1.25,foil_spec_um=1,foil_count=5" --package alpha.nuclemu
python -m nuclemu files inspect alpha.nuclemu
python -m nuclemu files export alpha.nuclemu --item ITEM_UUID --output reference.csv
python -m nuclemu files import alpha.nuclemu reference.csv --item ITEM_UUID --output alpha-with-reference.nuclemu
python -m nuclemu files inspect workbench.sqlite3
python -m nuclemu files convert-archive workbench.sqlite3 --archive ARCHIVE_ID --output converted.nuclemu
```

将 `ITEM_UUID` 换为 `files inspect` 输出中要选的项目 ID；检查旧 `workbench.sqlite3` 时会列出可供 `ARCHIVE_ID` 使用的档案标识。文件操作不依赖当前课程目录或当前运行的 Web 数据库。导入给新项目分配不同 ID，保留源身份，相同标题不会覆盖；只有显式改动分析选择才更换参考或本底。可重新导入的单项 CSV 带一行快照元数据；现有 `run --output` CSV 的结构保持不变。API、单项批量下载和 3 s/5 s 快照的重开示例见[可携实验文件](exchange.md)。

新版计数器整机记录按整套读数导出：`files export` 或 `files batch-export` 选到 A/B 任一成员 UUID，CSV、JSON 仍包含同次保存的 A/B，批量 ZIP 的成员名按整机生成，显式 `--output` 路径原样生效。读回后用 `files inspect` 的 `records` 首项 UUID 导入；直接传组内从项给 `files import` 仍会报错。没有整机关联的原生单窗文件继续按单窗处理。

`--output` 可重复，扩展名必须为 `.csv` 或 `.json`，目标父目录须已存在。输出不得指向 `--calibration` 的输入文件，包括相对路径和文件链接别名；发现冲突时，在采集、摘要和任何文件写出之前报错。默认导出全部设备；指定 `--device` 后只导出该设备。JSON 保留完整各段设置、整数计数、设备描述、种子和曝光边界；CSV 每段每道一行，包含设置、曝光及计数，载入刻度后另含 `energy_MeV`。摘要中的 ROI 和净率为派生读数，产品仍保存原始累计计数，供后续重新分析。

CLI 与浏览器工作台共用 `discover(paths)`、`catalog.describe(experiment)`、`Experiment.parameters/devices`、`Session` 和 `MeasurementView(session).product()`。装置中看到的参数键对应 CLI 的 `--set` 或 `--step`，部件绑定的仪器实例对应 `--device KIND:ID`。对齐时使用相同实验、种子、设备实例、参数变化顺序及每次开关门时刻；界面刷新可以拆分 `advance()`，不改变采集窗。CLI 每个 step 对应工作台一次定时采集；工作台的刷新、ROI、刻度和导出同样只消费现有产品。以相同产品的整数计数和曝光比较，避免把随机读数与模型期望率直接当作相等性条件。

运行入口验收：

```powershell
python -m unittest discover -s tests -p "test_cli*.py" -v
```

## 单轮调参与不同仪器窗长

新实验默认空源；有源采集须显式设置 `source_present=1` 并开启探测输出。`--window DEVICE=SECONDS` 可重复，为各仪器设置读数窗长。`--change "SECONDS,KEY=VALUE,..."` 的时刻从本轮开始计，必须严格位于 `--duration` 内；到时调用公共设置入口，采集门保持开启。相同时刻的参数写在同一个 change 中。它不与 `--step` 或 `--background` 混用。

```powershell
python -m nuclemu run beta --seed 42 --set source_present=1 --set foil_spec_um=100 --set foil_count=0 --enable-output beta_detector --window counter=1 --window counter_b=5 --duration 5 --change "2.5,foil_count=4" --package beta-windows.nuclemu
python -m nuclemu files inspect beta-windows.nuclemu
python -m nuclemu files export beta-windows.nuclemu --item ITEM_UUID --output counter-windows.csv
```

该轮 A 有五个 1 s 窗，B 有一个 5 s 窗。本课 A、B 按同一平均响应分别取样，是同工况的两组虚拟重复观测，不要求五短窗之和与同期一长窗相等或不同。按上述命令读取本次实得计数与实际曝光，并核对 A 第三窗保留换箔前后各 0.5 s 的工况。单项 JSON 保留 `windows`；单项 CSV 每窗每道一行，`parts` 保存窗内工况与原始计数，首行元数据保留累计工况段。无逐窗信息的旧文件按旧数据读取，不凭累计计数拆造窗口。普通 `run --output` 仍是累计工况段产品；需可重新载入的逐窗文件时使用 `--package` 后 `files export`。
