# -*- coding: utf-8 -*-
"""
分型识别 (课17/课62)。

在包含处理后的合并K线上, 任意相邻三根 (a, b, c):
    * 顶分型: b.high > a.high 且 b.high > c.high, 且 b.low > a.low 且 b.low > c.low;
    * 底分型: b.high < a.high 且 b.high < c.high, 且 b.low < a.low 且 b.low < c.low。
中间那根 b 即分型的极值K线。
"""
from __future__ import annotations

from typing import List

from .models import Fractal, FractalType, KLine, RawKLine


def find_fractals(merged: List[KLine], raws: List[RawKLine]) -> List[Fractal]:
    fractals: List[Fractal] = []
    for i in range(1, len(merged) - 1):
        a, b, c = merged[i - 1], merged[i], merged[i + 1]
        if b.high > a.high and b.high > c.high and b.low > a.low and b.low > c.low:
            kind = FractalType.TOP
        elif b.high < a.high and b.high < c.high and b.low < a.low and b.low < c.low:
            kind = FractalType.BOTTOM
        else:
            continue

        # 极值对应的原始K线 (绘图/MACD用)
        if kind is FractalType.TOP:
            raw_idx = max(b.elements, key=lambda j: raws[j].high)
        else:
            raw_idx = min(b.elements, key=lambda j: raws[j].low)

        fractals.append(Fractal(
            kind=kind,
            m_idx=i,
            high=b.high,
            low=b.low,
            left_idx=i - 1,
            right_idx=i + 1,
            raw_idx=raw_idx,
            dt=raws[raw_idx].dt,
        ))
    return fractals
