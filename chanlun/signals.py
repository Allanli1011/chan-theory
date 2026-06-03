# -*- coding: utf-8 -*-
"""
背驰判断与三类买卖点 (课17/课24/课29 中枢定理三)。

背驰 (课24): 相邻两段同向走势, 后段创新高/新低却力度(MACD柱面积: 向上看红、向下看绿)
更弱, 即背驰。背驰必制造某级别买卖点(背驰-买卖点定理)。本实现以【笔】为走势单元,
比较相邻同向笔(k-2 与 k)的 MACD 面积:后笔创新极值而面积明显变小即构成笔背驰。

三类买卖点 (课17/课24/中枢定理三):
  * 第一类: 趋势背驰导致的转折 —— 下跌背驰=一买(底), 上涨背驰=一卖(顶);
  * 第二类: 一类点后第一次回抽不破前低/前高 (买卖点定律一);
  * 第三类: 离开中枢的走势后, 次级别回抽不重新回到中枢区间 [ZD,ZG]
            (向上突破不回 ZG 之下 => 三买; 向下跌破不回 ZD 之上 => 三卖)。

同向连续背驰会做去重, 仅保留一段趋势中最极端(最终)的那个一类点。
"""
from __future__ import annotations

from typing import List

from .models import (BSPType, BuySellPoint, Direction, RawKLine, TrendType,
                     ZhongShu)
from .macd import MacdHelper


def classify_trend(zhongshus: List[ZhongShu]) -> TrendType:
    """据中枢数量与相对位置判定整体走势类型 (课17/课18)。"""
    if len(zhongshus) <= 1:
        return TrendType.CONSOLIDATION
    moves = []
    for a, b in zip(zhongshus, zhongshus[1:]):
        if b.ZD > a.ZG:
            moves.append(TrendType.UP)
        elif b.ZG < a.ZD:
            moves.append(TrendType.DOWN)
        else:
            return TrendType.CONSOLIDATION
    if moves and all(m is TrendType.UP for m in moves):
        return TrendType.UP
    if moves and all(m is TrendType.DOWN for m in moves):
        return TrendType.DOWN
    return TrendType.CONSOLIDATION


def _bsp(units, idx, kind, raws, reason, ratio=None) -> BuySellPoint:
    u = units[idx]
    return BuySellPoint(bsp_type=kind, raw_idx=u.raw_end, dt=raws[u.raw_end].dt,
                        price=u.end_value, reason=reason, beichi_ratio=ratio)


def _relevant_zhongshu_for_beichi(zhongshus, a, c, going_up):
    """背驰比较段是否关联并离开了某个中枢。"""
    for z in zhongshus:
        overlaps = a.raw_start <= z.raw_end and z.raw_start <= c.raw_end
        if not overlaps:
            continue
        if going_up and c.end_value > z.ZG:
            return z
        if not going_up and c.end_value < z.ZD:
            return z
    return None


def _second_point_index(units: List, k: int) -> int | None:
    """一类点后的首次反向走势, 再首次同向回抽/反抽。"""
    first_dir = units[k].direction
    opposite_seen = False
    for j in range(k + 1, len(units)):
        if not opposite_seen:
            if units[j].direction is first_dir.opposite:
                opposite_seen = True
            continue
        if units[j].direction is first_dir:
            return j
    return None


def _third_point_after_zhongshu(units: List, zs: ZhongShu):
    start = zs.elements[-1].idx + 1
    n = len(units)
    leave_idx = None
    leave_up = None
    for i in range(start, n):
        u = units[i]
        if u.direction is Direction.UP and u.high > zs.ZG and u.end_value > zs.ZG:
            leave_idx, leave_up = i, True
            break
        if u.direction is Direction.DOWN and u.low < zs.ZD and u.end_value < zs.ZD:
            leave_idx, leave_up = i, False
            break
    if leave_idx is None:
        return None

    for i in range(leave_idx + 1, n):
        u = units[i]
        if leave_up:
            if u.direction is not Direction.DOWN:
                continue
            if u.low > zs.ZG:
                return i, BSPType.BUY3, "向上突破中枢后回抽不回中枢(>ZG=%.1f)" % zs.ZG
            return None
        if u.direction is not Direction.UP:
            continue
        if u.high < zs.ZD:
            return i, BSPType.SELL3, "向下跌破中枢后回抽不回中枢(<ZD=%.1f)" % zs.ZD
        return None
    return None


def find_buy_sell_points(units: List, zhongshus: List[ZhongShu],
                         macd: MacdHelper, raws: List[RawKLine],
                         beichi_ratio: float = 0.9) -> List[BuySellPoint]:
    """在给定走势单元(默认笔)上识别全部买卖点。"""
    bsps: List[BuySellPoint] = []
    n = len(units)

    # ---- 第一类: 笔背驰 (相邻同向笔, 后笔创新极值且 MACD 面积更小) ----
    raw_sigs = []  # (k, is_up, ratio)
    for k in range(2, n):
        c, a = units[k], units[k - 2]
        if a.direction is not c.direction:
            continue
        up = c.direction is Direction.UP
        new_extreme = (c.end_value > a.end_value) if up else (c.end_value < a.end_value)
        if not new_extreme:
            continue
        if _relevant_zhongshu_for_beichi(zhongshus, a, c, up) is None:
            continue
        area_a = macd.directional_area(a.raw_start, a.raw_end, up)
        area_c = macd.directional_area(c.raw_start, c.raw_end, up)
        if area_a > 0 and area_c < area_a * beichi_ratio:
            raw_sigs.append((k, up, area_c / area_a))

    # 去重: 同方向连续背驰只保留最极端(价格最优)的一个
    first_pts = []  # (k, is_up, ratio)
    for k, up, ratio in raw_sigs:
        if first_pts and first_pts[-1][1] == up:
            pk = first_pts[-1][0]
            better = (units[k].end_value > units[pk].end_value) if up \
                else (units[k].end_value < units[pk].end_value)
            if better:
                first_pts[-1] = (k, up, ratio)
        else:
            first_pts.append((k, up, ratio))

    first_idx = {}
    for k, up, ratio in first_pts:
        tag = "趋势背驰"
        if up:
            bsps.append(_bsp(units, k, BSPType.SELL1, raws,
                             "上涨%s(后笔红柱面积更小)" % tag, ratio))
        else:
            bsps.append(_bsp(units, k, BSPType.BUY1, raws,
                             "下跌%s(后笔绿柱面积更小)" % tag, ratio))
        first_idx[k] = up

    # ---- 第二类: 一类点后第一次回抽不破前极值 (买卖点定律一) ----
    for k, up in first_idx.items():
        pull = _second_point_index(units, k)
        if pull is None:
            continue
        if not up and units[pull].end_value > units[k].end_value:
            bsps.append(_bsp(units, pull, BSPType.BUY2, raws, "一买后首次回抽不破前低"))
        elif up and units[pull].end_value < units[k].end_value:
            bsps.append(_bsp(units, pull, BSPType.SELL2, raws, "一卖后首次反抽不破前高"))

    # ---- 第三类: 离开中枢后回抽不回中枢 (中枢定理三) ----
    for zs in zhongshus:
        third = _third_point_after_zhongshu(units, zs)
        if third is None:
            continue
        pull, kind, reason = third
        bsps.append(_bsp(units, pull, kind, raws, reason))

    bsps.sort(key=lambda b: b.raw_idx)
    return bsps
