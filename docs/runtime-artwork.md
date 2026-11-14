# 运行时科学图像与来源

课程封面与设备图承担不同用途。封面解释物理主题；设备图帮助辨认工作台中的具体仪器。图像不提供实测数据，也不决定模型的操作或读数。

| 资产 | 用途与显示约定 |
|---|---|
| [α 能量损失封面](../nuclemu/static/cover-alpha-energy-loss.webp) | 960×600，不透明，按16:10完整显示；保留四核子符号及材料边界。 |
| [β 吸收封面](../nuclemu/static/cover-beta-absorption.webp) | 960×600，不透明，按16:10完整显示；同时保留入射较密与透射较稀的单电子符号。 |
| [双窗计数器](../nuclemu/static/rig-counter-dual.webp) | 426×480透明图，一台机箱内A/B两窗；使用contain，不能裁掉底脚或窗口。机箱边缘的示意接线锚点见同目录`apparatus-assets.json`。 |

## 示意边界

α封面的两红、两金球分别表示两个质子和两个中子，铝结构只用规则排列作材料示意，不是经几何校核的晶面重构。核子、原子与材料尺度不成比例。[ARPANSA：α粒子](https://www.arpansa.gov.au/understanding-radiation/what-is-radiation/ionising-radiation/alpha-particles)；[Nakashima：铝的晶体结构](https://arxiv.org/abs/2002.01562)。

β封面以单球表示β⁻电子，分开的铝片和逐渐稀疏的前向符号表示透射群体减少。粒子尺寸、点数、片厚、间隔和曲线均为定性示意，不能读出透射概率、能量、质量厚度或散射角，也不代表逐事件模拟。片间留白用于区分示意元素，不指定空气中的真实运动或散射位置。[NRC：辐射教学资料](https://www.nrc.gov/education-regulatory-research/the-student-corner/unit-1-radiation)；[NIST ESTAR：电子阻止本领与射程](https://physics.nist.gov/PhysRefData/Star/Text/ESTAR.html)。

封面旁可用短图注“跨尺度示意，非按比例”。可访问描述还应指出本课主体：α为四核子符号进入铝结构；β为电子符号穿过铝片后前向透射变稀。拖尾、颜色和点数均不作为仪器计数依据。

计数器为教学外观，不对应指定商用型号或真实尺寸；A/B为空白显示区，实时值由仪器页面提供。未标记的旋钮不承诺新增操作，图中没有真实电气接头。

## 制作与许可

三张图使用OpenAI内置ImageGen于2026年11月生成，最终运行时文件以Pillow导出无损WebP。α封面独立生成并修订；β封面只引用本项目α封面作为光照、材质与色彩参考；双窗图以本项目已有`rig-counter.webp`为参考生成并修订。上述科学网页仅用于核对事实，没有复制其图片。

图像沿用仓库的[GNU GPL第3版许可证](../LICENSE)。保留本说明与仓库许可，不主张AI生成内容具有排他的人类作者身份，也不对整个既有资源集合的来源作推断。独立美术维护的完整规范和资产索引见[素材PR #14](https://github.com/msjs2333/Nuclemu/pull/14)；运行时接入由工作台另行验收。

| 文件 | SHA-256 |
|---|---|
| `cover-alpha-energy-loss.webp` | `1ea6d43e8a5aa6822e1f8402c0ff126551d7639f823c435a1bd545c91c81ce1e` |
| `cover-beta-absorption.webp` | `f0af671316849722e977cdb08507754ddbe3295857dc296b4d18782881494794` |
| `rig-counter-dual.webp` | `1b40f7ff7540923829505b04b473c1c6929090f9a3eb5c80aaed903956474579` |
