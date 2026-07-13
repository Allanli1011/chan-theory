# TradingView 缠论指标 (Pine Script v6 移植)

[`chan_theory.pine`](chan_theory.pine) 是本仓库 `chanlun/` Python 流水线的 TradingView 移植版，
在图表上直接绘制 **笔 / 线段 / 中枢 / 三类买卖点**，算法与 Python 版逐模块对应：

| Pine 函数 | Python 模块 | 内容 | 课程出处 |
|---|---|---|---|
| `f_merge` | `cmerge.py` | K线包含处理 (高高/低低合并) | 课17/62 |
| `f_fractals` | `fractal.py` | 顶/底分型 | 课62 |
| `f_buildBis` | `bi.py` | 笔 (走势腿跟踪, `min_dist`) | 课62/65 |
| `f_buildSegments` 等 | `segment.py` | 线段 (特征序列 + 缺口两种情况) | 课65/67 |
| `f_zhongshus` | `zhongshu.py` | 走势中枢 (公共重叠延伸 / 同级别分解) | 课17/18 |
| `f_findBsps` | `signals.py` + `macd.py` | MACD 红绿柱面积背驰 + 一/二/三类买卖点 | 课17/24 |
| `f_classifyTrend` | `signals.py` | 走势类型 (上涨/下跌/盘整) | 课17 |

## 安装

1. 打开 [TradingView](https://www.tradingview.com/) 任意图表，底部打开 **Pine Editor**；
2. 把 `chan_theory.pine` 全文粘贴进去；
3. 点 **Add to chart / 添加到图表**。可用 "Save" 存到自己的指标库，之后任何图表都能加载。

## 图例

- **蓝色折线** = 笔；**黄色粗折线** = 线段（末段可能未终结，会随新K线变化）；
- **橙色矩形** = 笔中枢 `[ZD, ZG]`；紫色矩形 = 线段中枢（默认关闭）；
- **绿色标签**（K线下方）= 一买/二买/三买；**红色标签**（K线上方）= 一卖/二卖/三卖，
  悬停可见触发原因与背驰力度比；
- 右上角面板显示走势类型（中枢依次抬高=上涨 / 依次降低=下跌 / 否则盘整）与统计。

## 参数（与 Python 版默认值一致）

| 输入 | 默认 | 对应 Python 参数 |
|---|---|---|
| 笔最小间距 | 4 (标准笔；3=新笔) | `ChanAnalyzer(bi_min_dist=4)` |
| 背驰面积比阈值 | 0.9 | `beichi_ratio=0.9` |
| 中枢模式 | 中枢延伸 extension | `zhongshu_mode="extension"` / `"same_level"` |
| MACD 快/慢/信号 | 12/26/9 | `macd.py` |
| 最大分析K线数 | 3000 | —（Pine 端性能与绘图限制） |
| 仅在K线收盘后更新 | 关 | — |

## 警报

指标内置 `alert()`：新买卖点在最近 3 根K线内确认时触发。
在 TradingView 上对该指标 **创建警报 → 条件选 "任何 alert() 函数调用"** 即可推送到手机/邮箱。

## 与 Python 版的差异和注意事项

1. **计算窗口**：只分析最近 `最大分析K线数` 根K线（默认 3000，上限 9000）。TradingView
   本身按套餐限制历史K线数量；窗口起点不同可能使最早的一两笔与 Python 全量回算略有出入，
   越往后越收敛一致。
2. **MACD 一致性**：Pine 端 EMA 用"首值作种子"的递推，与 `macd.py` 的纯 numpy 回退实现
   完全一致（不是 TA-Lib 路径）；MACD柱 = `2*(DIF-DEA)`，同国内惯例。
3. **未收盘K线**：默认最后一根未收盘K线也参与计算，所以末端的笔/线段/信号会随盘中价格
   变化（这不是未来函数，只是"当下未确认"）。开启"仅在K线收盘后更新"可避免盘中跳动。
   缠论买卖点本身是**确认制**的：一个分型/笔要等右侧K线走出来才成立，历史信号不重绘。
4. **多级别**：Python 版的 `analyze_multi_level` 在 Pine 里对应"直接切换图表周期"——
   30分钟/日线/周线各开一个图表窗口即可，无需重采样。
5. **绘图对象上限**：中枢框最多画最近 120 个、买卖点标签最多最近 240 个、分型标记最近
   200 个（TradingView 每个指标 500 个对象的硬限制）。
6. 与 Python 版一样：线段采用课67特征序列有界确认，中枢默认公共重叠延伸模式；
   工程取舍的出处见仓库根目录 [FRAMEWORK.md](../FRAMEWORK.md)。

> ⚠️ 仅用于学习与研究缠论技术分析方法，不构成投资建议。
