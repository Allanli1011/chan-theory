# -*- coding: utf-8 -*-
"""
MACD 指标与"背驰"力度度量。

缠论用 MACD 辅助判断背驰 (课24《MACD对背驰的辅助判断》):
  * DIF  = EMA(close,12) - EMA(close,26)   (快线/白线)
  * DEA  = EMA(DIF,9)                       (慢线/黄线)
  * MACD柱 = 2 * (DIF - DEA)                (红绿柱)

背驰的本质是"力度"减弱。课程给出的可操作度量:
  1) 比较前后两段同向走势的 MACD 柱面积 (红/绿柱面积之和);
  2) 比较 DIF 黄白线触及的高低值;
后段面积/高度明显小于前段, 即构成背驰。

若安装了 TA-Lib 则用其 MACD, 否则用等价的纯 numpy EMA 实现。
"""
from __future__ import annotations

from typing import List, Tuple

import numpy as np

try:  # 优先使用 TA-Lib
    import talib  # type: ignore
    _HAS_TALIB = True
except Exception:  # noqa: BLE001
    _HAS_TALIB = False


def _ema(x: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1.0)
    out = np.empty_like(x, dtype=float)
    if len(out) == 0:
        return out
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return out


def compute_macd(close: np.ndarray, fast: int = 12, slow: int = 26,
                 signal: int = 9) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """返回 (DIF, DEA, MACD柱). MACD柱采用国内常用的 2*(DIF-DEA)。"""
    close = np.asarray(close, dtype=float)
    if len(close) == 0:
        empty = np.array([], dtype=float)
        return empty, empty, empty
    if not np.all(np.isfinite(close)):
        raise ValueError("close values must be finite")
    if _HAS_TALIB and len(close) >= slow:
        dif, dea, hist = talib.MACD(close, fastperiod=fast,
                                    slowperiod=slow, signalperiod=signal)
        dif = np.nan_to_num(dif)
        dea = np.nan_to_num(dea)
        macd = 2.0 * (dif - dea)
        return dif, dea, macd
    dif = _ema(close, fast) - _ema(close, slow)
    dea = _ema(dif, signal)
    macd = 2.0 * (dif - dea)
    return dif, dea, macd


class MacdHelper:
    """对一段原始K线计算并缓存 MACD, 提供区间面积/极值查询。"""

    def __init__(self, close: np.ndarray):
        self.close = np.asarray(close, dtype=float)
        self.dif, self.dea, self.macd = compute_macd(self.close)

    def area(self, i0: int, i1: int) -> Tuple[float, float]:
        """区间 [i0, i1] 内 MACD 红柱面积、绿柱面积 (均取正值)。"""
        i0, i1 = max(0, i0), min(len(self.macd) - 1, i1)
        seg = self.macd[i0:i1 + 1]
        red = float(np.sum(seg[seg > 0]))
        green = float(-np.sum(seg[seg < 0]))
        return red, green

    def directional_area(self, i0: int, i1: int, going_up: bool) -> float:
        """与走势方向一致的那种柱子的面积 (向上段看红柱, 向下段看绿柱)。"""
        red, green = self.area(i0, i1)
        return red if going_up else green

    def dif_extreme(self, i0: int, i1: int, going_up: bool) -> float:
        """区间内 DIF 的极值 (向上段取最大, 向下段取最小的绝对幅度)。"""
        i0, i1 = max(0, i0), min(len(self.dif) - 1, i1)
        seg = self.dif[i0:i1 + 1]
        if len(seg) == 0:
            return 0.0
        return float(np.max(seg)) if going_up else float(np.min(seg))
