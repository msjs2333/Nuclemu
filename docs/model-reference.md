# 教师与模型作者参考附录

本页列出 α 能损和 β 吸收两项实验的模型设定、期望读数和验收方法。学生操作说明见 [α 能损](alpha.md)与 [β 吸收](beta.md)。

<a id="alpha"></a>

## α 谱仪响应与质量射程

教学源选取三条主线，每条未停止谱线设置 25 s⁻¹ 的平均探测计数率。每窗按泊松分布抽样，对透射粒子的能量叠加标准差 0.012 MeV 的高斯响应。电子学线性映射的斜率为 0.006 MeV/道，截距为零。程序将读数舍入到最近的道号，舍弃非正能量和超量程读数。该响应在不同箔厚下保持一致。模拟省略实际支线、分支比及堆积。[参考源主线](https://www.ezag.com/products/isotope-products/isotrak-calibration-sources/reference-sources/alpha-spectroscopy-sources/)

`nuclemu/experiments/alpha.py` 的 `RANGE_TABLE` 选取铝的 ASTAR 默认能量节点，保留 0.001–6 MeV 的动能和 CSDA 质量射程，单位分别为 MeV 和 g/cm²。程序采用分段线性插值计算 `R_remaining = max(0, R(E_incident) − x)`，其中 `x` 为铝箔面密度，再从同一表反插值得到剩余能量。原点是模型添加的停止边界。0 至 0.001 MeV 区间线性连接原点，模型有效上限为 6 MeV。数据核对日期为 2026-11-11。[NIST 铝射程表入口](https://physics.nist.gov/PhysRefData/Star/Text/ASTAR-t.html) · [NIST 方法与列定义](https://physics.nist.gov/PhysRefData/Star/Text/programs.html)

核对单位时可使用 `R(5.0 MeV) = 0.005825 g/cm²` 与 `R(5.5 MeV) = 0.006678 g/cm²`。在该模型中，入射 5.5 MeV 的 α 粒子穿过 0.000853 g/cm² 的铝后剩余 5.0 MeV。材料对象采用密度 2.70 g/cm³，5 µm 对应 0.00135 g/cm²。[NIST 铝材料数据](https://physics.nist.gov/cgi-bin/Star/compos.pl?ap-text013)

下表给出表插值预测的透射能量，单位为 MeV。

| 铝箔厚度 / µm | 5.155 MeV 线 | 5.486 MeV 线 | 5.805 MeV 线 |
| --- | ---: | ---: | ---: |
| 0 | 5.155 | 5.486 | 5.805 |
| 5 | 4.307 | 4.674 | 5.033 |
| 15 | 2.182 | 2.694 | 3.173 |
| 25 | 停止 | 停止 | 0.423 |
| 30 | 停止 | 停止 | 停止 |

用零箔谱的两个外峰拟合刻度，再用独立的中峰检查刻度。60 s 曝光下，无箔时平均总计数为 4500，25 µm 时为 1500，单次采集有统计涨落。专项测试覆盖峰移、部分停止和完全停止。[α 验收测试](../tests/test_alpha.py)

<a id="beta"></a>

## β 计数器的有效吸收曲线

固定源窗、几何接受度和探测效率均已计入参考净率。对有源工况，总率为 `R = B + S₀ × 2^(−m/H)`，本底工况仅保留 `B`。各窗按期望值 `R × t` 抽取整数计数，其中 `t` 为实际曝光秒数。本底率 `B = 2 s⁻¹`，无附加箔时净率 `S₀ = 100 s⁻¹`，有效半值面密度 `H = 0.112 g/cm²`。默认 100 µm/片对应面密度 0.027 g/cm²，50 µm/片对应 0.0135 g/cm²；均为课程选定的 Al 规格。下表固定为默认 100 µm/片。

| 铝箔片数 | 期望总计数率 / s⁻¹ |
| ---: | ---: |
| 0 | 102.00 |
| 4 | 53.25 |
| 8 | 28.27 |
| 16 | 8.90 |

半值面密度取自 Chou 与 Tung 对 Sr-90/Y-90 射线经铝过滤后在较大厚度区测得的剂量衰减尺度。该论文使用电离室测量剂量响应。这里借用其数值作为虚拟计数器的教学参数，归一计数率、探测效率和适用厚度范围由实验设定。验收时可按片数检查计数均值、方差和不同曝光下的本底扣除。学生导出的原始计数允许独立复算。[Chou 与 Tung 的实验论文](https://doi.org/10.1093/oxfordjournals.rpd.a031576) · [β 验收测试](../tests/test_beta.py)

文献的公开摘要还报告了薄层处剂量响应的增长及厚层处的近似指数段，因此该教学式不描述真实裸源在所有厚度处的响应，也不是完整的 β 连续能谱输运或电子最大射程模型。当前只在固定源窗、几何与阈值下、总附加厚度 0–2.4 mm 的 Al 上使用；不据此外推其他材料、可变探测距离或探测阈值。探测开关关闭时由公共采集层给零输入，而不是把 `B` 也理解成空源座消失。

公开来源：T. L. Chou、C. J. Tung，*Absorption and Scattering of 90Sr/90Y Beta Particles Transmitted Through Aluminium and Plastic Filters*，*Radiation Protection Dosimetry* 64(3), 213–220 (1996)，[期刊摘要和文献信息](https://academic.oup.com/rpd/article-abstract/64/3/213/1633227)。另可参阅 [CAEN 的 β 透射教学实验](https://edu.caen.it/experiments/nuclear-physics/beta-radiation-transmission-through-matter/)对指数近似区间的说明。两项公开页面于 2026-11-12（香港）核对；数值设置仍以本项目模型代码为准。
