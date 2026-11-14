# 可携实验文件与单项交换

整场交付使用 `.nuclemu`：它是可解压的 ZIP，内含 `manifest.json` 和 `experiment.sqlite3`，不依赖本机的 `workbench.sqlite3`。清单声明 `nuclemu.package/1`、版本 1、SQLite 文档结构 `nuclemu.experiment/1`、实验与包标识、数据库文件名及 SHA-256。打开时核对版本、身份和数据库内容。所有资源由标准库离线读写。

## 保存什么

SQLite 将末态与目录放在 `manifest` 表，轮次元数据放在 `rounds`，手动缓存项目的描述放在 `items`，测量段放在 `segments`。包中的单位来自归档实验定义与产品；计数为整数，曝光和物理时间以 s 为单位，谱刻度能量为 MeV。

`capture_session()` 读取 `Session.rounds`、`configuration_history` 和明确保存到 `Session.snapshots` 的快照，不读取未缓存的 `records` 或当前累计道谱。仪器的门状态、模式、目标、窗长和曝光可作为末态元数据保存，当前未缓存计数不随末态落盘。

例如：3 s 时保存一份 60 次的快照，继续采到 5 s，整场文件可以包含轮次曝光 5 s，但这份谱仍是 60 次、3 s，其率为 20 s⁻¹。若 5 s 再主动保存，则有两份各自独立命名的累计快照，两者可重叠，不能作为独立测量相加。另一轮全程没有保存时，仅有工况历史与曝光，没有伪造的零计数记录。

单项记录使用 UUID，保留包来源与原项目身份；`snapshot.id` 仍保留内核的本机会话编号。仪器与同轮身份、保存时刻和实际截止曝光保存在测量产品的 `snapshot` 中。原生项目和导入参考分别识别，同包导出再回导也不会向内核恢复两个同编号快照。

双窗计数器的一次整机保存沿用这些测量项：仅首项增加 `group={"items": [首项及同次测量项的 UUID], "members": [整机设备 ID]}`。首项 UUID 就是这份读数的选择身份，没有另一套记录实体。两窗各自保留曝光、计数、完整窗与实际部分窗；例如 A 取 1 s、B 取 5 s，3 s 保存时，A 有三行完整窗，B 有一行 3 s 的 `complete=false` 部分窗，不补成 5 s。真正没有曝光的一侧没有测量项，`members` 仍说明这是一次整机保存。没有 `group` 的历史单窗文件按原样读取和导入，不按名字或时刻配对。

`list_items(doc)` 继续提供每个单项；学生记录表使用 `list_records(doc)`，将同次保存投影为首项的一行，带各侧的 `measurements` 摘要。`rename_record(doc, id, title)` 按稳定 UUID 改名，同次成员一起更新；名字相同不影响分析引用、载入或下载。新保存的默认名由 `default_record_name(definition)` 生成实验缩写和实际保存时间，调用方可在保存前用 `validate_record_name()` 核对用户输入。

手动保存刻度使用 `cache_calibration()`。通过 `bind_calibration()` 把测量项目关联到已保存、设备与工况相符的刻度，不将后来未保存的当前刻度自动附给旧谱。分析的 `reference`、`background` 和 `selected` 引用项目 UUID，不能使用实时产品的段下标。

## 公共 Python 调用

```python
from nuclemu.catalog import discover
from nuclemu.core import Session
from nuclemu.exchange import capture_session, save_package, load_package, reopen_session

experiment = discover()["alpha"]
s = Session(experiment, seed=187)
s.set_output("alpha_detector", True)
s.set("source_present", 1)
s.start(5, device="mca")
s.advance(3)
s.snapshot("mca")                 # 学生主动保存，曝光 3 s
s.advance(2)                       # 尚未主动保存的尾部不会进入文件
doc = capture_session(s)
save_package("alpha.nuclemu", doc)

loaded = load_package("alpha.nuclemu")
fresh = reopen_session(loaded, experiment)
assert fresh.instrument("mca").exposure_s == 0
fresh.set_output("alpha_detector", True)
fresh.start(1, device="mca")
fresh.advance(1)
fresh.snapshot("mca")
doc = capture_session(fresh, loaded)  # 保留旧项目及其身份，新增第二轮的 1 s 快照
```

打开文件本身不执行模型或结清采集窗。`reopen_session()` 经公共 `Session.reopen()` 载入已验证的规范设置、历史轮次和缓存快照。所有门与探测输出均关闭，当前仪器从零曝光开始；按开始后建立新轮，编号接续。保留既有仪器目标和窗长，但不恢复未缓存的当前计数。顶层 `random_stream` 保存根种子、派生规则和代数；重开时增加代数，生成新统计流。旧文件没有该字段时按初代处理。保存的观测保持原值，同一文件按相同操作重开仍可复现；不能称作原随机流的精确续跑。

完整可跑例：

```powershell
python -m examples.portable_experiment --directory portable-output
```

该例实际保存 α 同轮两份参考谱：种子 187 下为 221 次/3 s、375 次/5 s，另存实测峰心建立的刻度；把 `.nuclemu` 复制到另一目录后重开，核对全部项目，再开始第二轮 1 s。例中同时写出第一份谱的 JSON 和 CSV，并将其作为参考导入一个新实验。省略 `--directory` 时使用临时目录，完成后清理。

## Web 与 CLI 共用的下载和导入

`package_download(doc)` 返回整场文件的 `(文件名, MIME, bytes)`，名称为 `{CODE}_{YYYYMMDD-HHMMSS-ffffff}.nuclemu`；它不接受记录勾选列表，始终包含全部手动缓存和元数据。`CODE` 来自目录的 `short_code`，内置 α 为 `AEL`、β 为 `BABS`。时间是本机实际保存时刻，精确到微秒，不取仿真时刻；同进程遇到相同或回退的系统时间时，按上一名称递增一微秒，重复下载无需推进仿真。

`batch_download(doc, [{"id": item_id, "format": "csv"}, ...])` 只导出指定项目。内置课程的单项名称采用 `{CODE}_{时间}_spectrum.csv`、`{CODE}_{时间}_calibration.json`、`{CODE}_{时间}_counts-A.csv` 或 `counts-B.csv`；谱和计数也支持 JSON。窗字母按课程装置绑定的顺序取得，外部同类多设备需要区分时附安全实例名。多项返回 `{CODE}_{时间}_records.zip`，成员沿用同批次时间并加顺序号去重，项目可分别选择格式。UUID 仅保留在文件内部。旧协议下载同样使用课程代码与真实保存时间，测量标签可附 `segment-N` 或 `segments`。默认主名与批量成员均不加 `nuclemu` 前缀；专有整场扩展名保留 `.nuclemu`。CLI 显式指定的输出路径原样生效。这些名称不改变文件内部的包、记录或来源身份。旧包缺少 `short_code` 时，当前工作台使用已安装课程的目录代码命名，不改原包。

```python
from nuclemu.exchange import export_item, load_item, import_item

identity = loaded["items"][0]["id"]
data = export_item(loaded, identity, "csv")
bundle = load_item(data)
new_id = import_item(doc, bundle, identity)
```

单项 JSON 包含所选项目及所依赖的刻度。单项 CSV 第一行以 `# ` 开头，保存 `nuclemu.item/1` 元数据与刻度关联；后续是标准列名和各道整数计数。第三方表格工具可以跳过第一行读计数；Nuclemu 读回时使用它恢复快照身份、截止曝光和刻度。全道谱保留零计数道，缺道、重道或曝光不符会报错。普通 `run --output` 保持既有无元数据行的测量 CSV，供外部分析；需要可重新导入的单项文件时，使用本节的导出。

`import_item()` 完成校验后追加新 UUID 并保留源标识和刻度依赖。相同名称不覆盖已有项目；当前仪器及未保存读数不变。分析引用由调用方在导入成功后显式选择，不会因导入而自动改换本底或参考谱。导入来自不同实验或不符的设备类型/道数时明确报错。

## 逐窗数据与载入仪器

测量产品的 `windows` 保留窗口编号、累计曝光边界、整数计数、完整或未完成状态、该窗原定 `window_s`，以及窗内各工况的 `parts`。单项 CSV 每窗每道一行，`parts` 列保留窗内设置与原始读数；首行元数据同时保留累计工况段，读回时核对两种视图的工况、计数和曝光一致。缺少窗口字段的旧文件不凭累计读数拆造逐窗计数；载入后以 `window_prefix` 保存缺明细部分的累计曝光和计数，后续只追加真实新窗。窗口编号从已知窗口的 1 开始，不能称旧累计曝光为若干已测窗口。

运行中改窗长记录为轮次 `window_changes`，保留请求时刻和实际生效曝光；当前窗按原定长度结清后才使用新长度。`instruments.next_window_s` 保存待生效值，重开待机时把它作为预设，不恢复未结清的现场窗。载入部分窗口时保留其原定长度，继续到原边界后才使用目标仪器的后续窗长。

```python
from nuclemu.exchange import decode_measurement

decoded = decode_measurement("reference-3s.csv", experiment, "mca")
# 多份测量的包或缓存还须传 item_id，不能自动猜选最后一份。
fresh.load_measurement("mca", decoded.snapshot)
# 仪器已有曝光时须先由界面确认，再显式 overwrite=True。
fresh.set_output("alpha_detector", True)
fresh.start(device="mca")
fresh.advance(1)
```

`decode_measurement()` 无现场副作用，返回冻结的 `DecodedMeasurement(snapshot, calibration, source, item_id, title)`，统一检查实验、设备绑定、道数和刻度关联。记录页的 `import_item()` 只追加缓存；仪器载入使用 `Session.load_measurement()`，仅替换目标仪器，保持其他仪器和本场硬件设置。已有曝光即为非空，合法零计数也须确认覆盖。

整机使用 `decode_measurements(source, experiment, devices, record_id=None)`，返回实际保存成员的 `DecodedMeasurement` 元组，再由整机载入接口一次应用。它不修改现场；旧单项仍只返回一份，不猜另一窗。对成组保存的首项调用 `export_item()`、`import_item()` 或 `batch_download()`，会一起处理同次保存的实际成员和必要刻度。JSON、CSV 和实验包均保留首项关联；CSV 的 `item`、`device` 列区分成员，各侧窗口编号分别从 1 开始。导入重分配既有项 UUID 并改写首项关联，原始 `source` 不变。

CLI 的 `files inspect` 同时给出单项 `items` 和学生记录视图 `records`；`files export/import --item UUID` 接受成组首项或历史单项 UUID。`run --package` 在未指定单设备时将同次保存的计数器读数组合在首项。改名与混合格式批量下载可直接执行：

```powershell
python -m nuclemu files rename experiment.nuclemu --item UUID --title "样品读数" --output renamed.nuclemu
python -m nuclemu files batch-export experiment.nuclemu --item UUID:csv --item OTHER_UUID:json --output selected.zip
```

批量只选一项时写该项内容，多项写 ZIP；显式输出路径原样使用。组内成员、同名记录及不同格式的 ZIP 名称用批内序号区分。

载入的已测曝光是固定前缀。旧段与旧窗口保留原始时刻和工况，新窗按本场时钟记录，累计曝光和窗号连续。段的 `origin` 区分来源时间线；缺省表示本场。`snapshot.source` 标识载入记录，轮次 `loaded_exposure_s`/`loaded_source` 记录前缀来源与曝光。源记录在 100–103 s 测得的三窗可在本场 0 s 载入并续采至四窗；本场时间不会跳到 103 s。单项文件和整场重开保留这些扁平来源标识，不嵌套整份原档。

测量段和统计窗的 `parts` 可带有 `signal`。`input` 是取得这段读数的输出端口，`consumers` 列出当时绑定该端口的仪器读数通道。判断两窗是否观测同一输入，需要同时核对来源实验、时间区间和端口。历史共享双窗各自导出的文件会保留相同的端口与两个消费者；在当前独立双窗中续采后，新段各自只列一个消费者。若早期转存已丢失原输入绑定，对应历史段的 `signal` 缺省，表示该信息未知。

## 既有内部档案转存

`convert_archive("workbench.sqlite3", archive_id)` 只读旧库 `archives/segments`，转换一个独立保存的实验。旧档原有测量已经是已存观测，转存时全部保留，不按新实时设置重算。原始定义、末态与完整旧产品还保留在 `legacy.document` 中，便于逐道核对。

α 旧档的 `foil_um=2.5` 始终是原始总厚度 2.5 µm，不补成新规格或片数，不经实时设置转换；旧固定两点刻度保持原值。旧档可离线查看和作为参考导入；若要开始新的实测，先建立当前课程的合法新实验再导入需要的观测，不能用旧厚度重建新模型。

在工作台用“载入实验”打开转存的 `.nuclemu`，可离线查看原始设置、曝光、谱及其刻度，从“实验记录”下载所选读数。要把某一份历史观测加进当前课程的缓存，可在“实验记录”中导入转存包，再选择所需记录。转存文件保留独立于原库的原始数据，旧段下标分析选择映射为相应记录的 UUID。

## 验证

```powershell
python -m unittest discover -s tests -p test_exchange.py -v
python -m unittest discover -s tests -p "test_cli*.py" -v
```

专项包含 3 s 快照/5 s 轮次、同轮两份快照分别导出、未保存轮次只含元数据、另一目录离线重开、新轮零曝光、同名及同包回导、刻度关联、目标变更历史、旧厚度保留、损坏实验/设备绑定拒绝和写入失败保留原文件。浏览器的具体菜单与确认流程由 Web 工作台接入后另行验收。
