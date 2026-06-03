# -*- coding: utf-8 -*-
"""
K线包含处理 (合并) —— 缠论一切分析的预处理 (课17/课62)。

包含关系: 相邻两K线中, 一根的 [low, high] 完全被另一根包含。
处理规则 (方向由"被包含前的走势方向"决定):
    * 向上处理: 取两者 high 的较大者、low 的较大者 (高高);
    * 向下处理: 取两者 high 的较小者、low 的较小者 (低低)。
合并方向取决于当前已合并序列的最后两根: last.high > prev.high 视为向上, 否则向下。
"""
from __future__ import annotations

from typing import List

from .models import Direction, KLine, RawKLine


def _included(h1: float, l1: float, h2: float, l2: float) -> bool:
    """判断两区间是否存在包含关系 (任一方向)。"""
    return (h1 >= h2 and l1 <= l2) or (h2 >= h1 and l2 <= l1)


def merge_klines(raws: List[RawKLine]) -> List[KLine]:
    """对原始K线做包含处理, 返回合并后的 KLine 列表。"""
    merged: List[KLine] = []
    last_dir = Direction.UP  # 序列起始无趋势, 约定默认向上

    for r in raws:
        if not merged:
            merged.append(KLine(idx=0, high=r.high, low=r.low,
                                elements=[r.idx], direction=last_dir))
            continue

        last = merged[-1]
        if not _included(last.high, last.low, r.high, r.low):
            # 无包含: 直接新增, 并更新方向
            if r.high > last.high:
                last_dir = Direction.UP
            elif r.high < last.high:
                last_dir = Direction.DOWN
            merged.append(KLine(idx=len(merged), high=r.high, low=r.low,
                                elements=[r.idx], direction=last_dir))
            continue

        # 存在包含: 按当前方向合并到 last
        if len(merged) >= 2:
            direction = (Direction.UP if last.high > merged[-2].high
                         else Direction.DOWN)
        else:
            direction = last_dir

        if direction is Direction.UP:
            last.high = max(last.high, r.high)
            last.low = max(last.low, r.low)
        else:
            last.high = min(last.high, r.high)
            last.low = min(last.low, r.low)
        last.elements.append(r.idx)
        last.direction = direction
        last_dir = direction

    # 规范 elements 顺序
    for k in merged:
        k.elements.sort()
    return merged
