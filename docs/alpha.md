# α 粒子在铝箔中的能量损失

实验 `alpha` 使用 1024 道硅谱仪 `mca`，道号为 0–1023。在固定源、铝箔与探测器几何下，调节铝箔厚度 `foil_um`（0–40 µm），测量同一条 α 谱线的峰位随厚度的变化。采集时长按工作台的仿真时钟计。

## 测量与刻度

1. 将 `foil_um` 设为 0，采集参考谱。教学源选取 Pu-239、Am-241、Cm-244 各一条主线，能量依次为 5.155、5.486、5.805 MeV。在每个峰两侧选定只覆盖该峰的道区（ROI），用区内各道的计数作权重计算峰心。[α 能谱参考源表](https://www.ezag.com/products/isotope-products/isotrak-calibration-sources/reference-sources/alpha-spectroscopy-sources/)
2. 取两端峰的实测峰心 `c1`、`c2` 和相应的参考能量 `E1`、`E2` 建立线性刻度。用中间峰的峰心换算能量，再与 5.486 MeV 比较。保留参考谱和本次刻度。
3. 加入铝箔并重新采集，沿厚度递增的顺序跟踪同一条谱线。随峰移动调整 ROI，继续使用参考谱的刻度。记录厚度、曝光、选区、实测峰心和对应能量。如果峰区计数为零，记录零计数并将峰位留空。

```text
b = (E2 - E1) / (c2 - c1)               # MeV/channel
E(c) = E1 + b * (c - c1)
ΔE = b * (c_without_foil - c_with_foil) # MeV
```

刻度绑定实验、设备实例和道数。在同一仪器上更换铝箔时仍可使用这份刻度。道谱和刻度可分别保存，便于重新选区。[图形实验台](gui.md) · [命令行](cli.md)

## 用射程数据解释峰移

在 NIST ASTAR 中选择铝（Aluminum，材料号 013），用连续减速近似（CSDA）的质量射程 `R`，单位为 g/cm²。由无箔和加箔的实测峰能量估计穿过的面密度 `R(E_without_foil) − R(E_with_foil)`。两者采用相同单位时，可与几何面密度 `2.70 × foil_um × 10⁻⁴ g/cm²` 对照，这里取铝密度为 2.70 g/cm³。[NIST ASTAR](https://physics.nist.gov/PhysRefData/Star/Text/ASTAR-t.html) · [NIST 列定义](https://physics.nist.gov/PhysRefData/Star/Text/programs.html) · [铝材料数据](https://physics.nist.gov/cgi-bin/Star/compos.pl?ap-text013)

本实验描述均匀纯铝箔中法向入射粒子的平均能损，采用固定几何和固定谱仪响应。模型忽略多重散射、能损涨落、空气和探测器死层损失、死时间及本底。接近停止厚度时，模型采用确定性的射程截止，因此实测趋势适于讨论峰移和停止，不能据此估计真实粒子的透射概率。

教师备课或核对模型实现时可查阅[教师与模型作者参考附录](model-reference.md#alpha)。
