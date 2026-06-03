# -*- coding: utf-8 -*-
"""
笔的划分 (课62《分型、笔与线段》, 课65)。

笔: 连接相邻的一个顶分型与一个底分型, 方向由低到高为向上笔, 由高到低为向下笔。

成立条件 (标准笔/老笔):
    顶分型与底分型不能共用K线, 且两者之间至少还有 1 根独立的合并K线。
    等价地: 顶、底分型"中心"合并K线的下标之差 >= 4
    (即从一个分型极值到下一个分型极值, 含两端至少 5 根合并K线)。
可通过 min_dist 调整 (新笔可取 3)。

划分算法 (贪心确认端点):
    遍历分型, 维护交替的端点序列:
      * 遇到同类分型 -> 保留更极端者 (更高的顶 / 更低的底);
      * 遇到异类分型且满足间距 -> 确认成笔, 加为新端点;
      * 异类但间距不足 -> 若它比上上个同类端点更极端, 则回退替换, 否则忽略。
"""
from __future__ import annotations

from typing import List

from .models import Bi, Direction, Fractal, FractalType, KLine, RawKLine


def _more_extreme(a: Fractal, b: Fractal) -> bool:
    """a 是否比 b 更极端 (同类分型: 顶更高 / 底更低)。"""
    if a.kind is FractalType.TOP:
        return a.value > b.value
    return a.value < b.value


def build_bis(fractals: List[Fractal], merged: List[KLine],
              raws: List[RawKLine], min_dist: int = 4) -> List[Bi]:
    """走势腿(leg)跟踪法划分笔。

    维护交替的端点序列, 处理每个新分型:
      * 与当前端点同类 -> 延伸该腿极值(保留更极端者), 并把端点位置前移到新极值;
      * 与当前端点异类:
          - 间距(中心K线下标差) >= min_dist 且价格关系成立 -> 确认转折, 作为新端点;
          - 否则为次级别噪声, 暂忽略; 但若它比上一个同类端点更极端, 说明上一端点是
            假转折, 回退之并以更极端者替换 (避免漏掉真正的极值)。
    这样既能过滤小幅波动, 又能保留真实高低点 (课62/课65)。
    """
    if len(fractals) < 2:
        return []

    endpoints: List[Fractal] = [fractals[0]]
    for fx in fractals[1:]:
        last = endpoints[-1]
        if fx.kind is last.kind:
            if _more_extreme(fx, last):
                endpoints[-1] = fx
            continue

        gap = fx.m_idx - last.m_idx
        valid_price = (fx.value > last.value) if last.kind is FractalType.BOTTOM \
            else (fx.value < last.value)
        if gap >= min_dist and valid_price:
            endpoints.append(fx)
            continue

        # 间距不足: 仅当 fx 突破了上一个同类端点(假转折)时才回退, 否则忽略
        if len(endpoints) >= 2 and _more_extreme(fx, endpoints[-2]):
            endpoints.pop()
            if _more_extreme(fx, endpoints[-1]):
                endpoints[-1] = fx

    bis: List[Bi] = []
    for a, b in zip(endpoints, endpoints[1:]):
        if a.kind is b.kind:
            continue
        direction = Direction.UP if a.kind is FractalType.BOTTOM else Direction.DOWN
        bis.append(Bi(
            direction=direction,
            fx_a=a, fx_b=b,
            m_start=a.m_idx, m_end=b.m_idx,
            raw_start=a.raw_idx, raw_end=b.raw_idx,
            idx=len(bis),
        ))
    return bis
