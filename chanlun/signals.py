# -*- coding: utf-8 -*-
"""
背驰判断与三类买卖点 (课17/课24/课27/课29 中枢定理三)。

背驰 (课24): 相邻两段同向走势, 后段创新高/新低却力度(MACD柱面积: 向上看红、向下看绿)
更弱, 即背驰。背驰必制造某级别买卖点(背驰-买卖点定理)。本实现以走势单元(笔或线段)
比较相邻同向单元(k-2 与 k)的 MACD 面积: 后段创新极值而面积明显变小即构成背驰。

趋势背驰与盘整背驰的区分 (课17/24/27):
  * 趋势背驰: 背驰的关联中枢之前存在依次同向排列的前一中枢 (即处于趋势末端),
    才构成严格的第一类买卖点;
  * 盘整背驰: 关联中枢存在但其前无同向前中枢 —— 单独标注 (PZBUY/PZSELL),
    不计入三类买卖点 (课27 用其判断盘整结束与历史性底部, 课29 讨论其转化)。

三类买卖点 (课17/课24/中枢定理三):
  * 第一类: 趋势背驰导致的转折 —— 下跌背驰=一买(底), 上涨背驰=一卖(顶);
  * 第二类: 一类点后第一次回抽不破前低/前高 (买卖点定律一);
  * 第三类: 离开中枢的走势后, 次级别回抽不重新回到中枢区间 [ZD,ZG]
            (向上突破不回 ZG 之下 => 三买; 向下跌破不回 ZD 之上 => 三卖)。

同向连续背驰在各自类别内去重, 仅保留价格最极端(最终)的那个。
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


def _bsp(units, idx, kind, raws, reason, ratio=None,
         ref_zs: ZhongShu | None = None, level: str = "bi",
         src_raw_start: int | None = None) -> BuySellPoint:
    u = units[idx]
    ref_kwargs = {}
    if ref_zs is not None:
        ref_kwargs = {
            "ref_zs_idx": ref_zs.idx,
            "ref_zs_zd": ref_zs.ZD,
            "ref_zs_zg": ref_zs.ZG,
            "ref_zs_raw_start": ref_zs.raw_start,
            "ref_zs_raw_end": ref_zs.raw_end,
        }
    return BuySellPoint(bsp_type=kind, raw_idx=u.raw_end, dt=raws[u.raw_end].dt,
                        price=u.end_value, reason=reason, beichi_ratio=ratio,
                        level=level, src_raw_start=src_raw_start,
                        **ref_kwargs)


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


def _is_trend_beichi(zhongshus, z, going_up):
    """背驰是否处于趋势末端 (课17/24/27)。

    严格的第一类买卖点来自【趋势】背驰: 关联中枢 z 之前须有依次同向排列的
    前一中枢 (上涨: z.ZD > 前中枢.ZG; 下跌: z.ZG < 前中枢.ZD)。
    否则为【盘整】背驰。
    """
    zi = next((i for i, zz in enumerate(zhongshus) if zz is z), -1)
    if zi <= 0:
        return False
    prev = zhongshus[zi - 1]
    return (z.ZD > prev.ZG) if going_up else (z.ZG < prev.ZD)


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
                return (
                    i,
                    BSPType.BUY3,
                    "向上突破中枢后回抽不回中枢(ZS%d, price>ZG=%.4g)" %
                    (zs.idx, zs.ZG),
                    zs,
                )
            return None
        if u.direction is not Direction.UP:
            continue
        if u.high < zs.ZD:
            return (
                i,
                BSPType.SELL3,
                "向下跌破中枢后反抽不回中枢(ZS%d, price<ZD=%.4g)" %
                (zs.idx, zs.ZD),
                zs,
            )
        return None
    return None


def find_signals(units: List, zhongshus: List[ZhongShu],
                 macd: MacdHelper, raws: List[RawKLine],
                 beichi_ratio: float = 0.9, level: str = "bi"):
    """在给定走势单元(笔或线段)上识别信号。

    返回 (bsps, pzbcs):
      * bsps  —— 一/二/三类买卖点 (一类点要求趋势背驰, 课17/24/27);
      * pzbcs —— 盘整背驰提示点 (PZBUY/PZSELL, 课24/27), 不属于三类买卖点。
    """
    bsps: List[BuySellPoint] = []
    pzbcs: List[BuySellPoint] = []
    n = len(units)
    unit_name = "笔" if level == "bi" else "段"

    # ---- 背驰扫描 (相邻同向单元, 后段创新极值且 MACD 面积更小) ----
    raw_sigs = []  # (k, is_up, ratio, is_trend)
    for k in range(2, n):
        c, a = units[k], units[k - 2]
        if a.direction is not c.direction:
            continue
        up = c.direction is Direction.UP
        new_extreme = (c.end_value > a.end_value) if up else (c.end_value < a.end_value)
        if not new_extreme:
            continue
        z = _relevant_zhongshu_for_beichi(zhongshus, a, c, up)
        if z is None:
            continue
        area_a = macd.directional_area(a.raw_start, a.raw_end, up)
        area_c = macd.directional_area(c.raw_start, c.raw_end, up)
        if area_a > 0 and area_c < area_a * beichi_ratio:
            raw_sigs.append((k, up, area_c / area_a,
                             _is_trend_beichi(zhongshus, z, up)))

    # 各类别内去重: 同方向连续背驰只保留最极端(价格最优)的一个
    def _dedup(sigs):
        out = []  # (k, is_up, ratio)
        for k, up, ratio in sigs:
            if out and out[-1][1] == up:
                pk = out[-1][0]
                better = (units[k].end_value > units[pk].end_value) if up \
                    else (units[k].end_value < units[pk].end_value)
                if better:
                    out[-1] = (k, up, ratio)
            else:
                out.append((k, up, ratio))
        return out

    trend_pts = _dedup([(k, up, r) for k, up, r, t in raw_sigs if t])
    pz_pts = _dedup([(k, up, r) for k, up, r, t in raw_sigs if not t])

    # ---- 第一类: 趋势背驰 ----
    first_idx = {}
    for k, up, ratio in trend_pts:
        if up:
            bsps.append(_bsp(units, k, BSPType.SELL1, raws,
                             "上涨趋势背驰(后%s红柱面积更小)" % unit_name, ratio,
                             level=level, src_raw_start=units[k].raw_start))
        else:
            bsps.append(_bsp(units, k, BSPType.BUY1, raws,
                             "下跌趋势背驰(后%s绿柱面积更小)" % unit_name, ratio,
                             level=level, src_raw_start=units[k].raw_start))
        first_idx[k] = up

    # ---- 盘整背驰: 单独标注, 不计入三类买卖点 (课24/27) ----
    for k, up, ratio in pz_pts:
        kind = BSPType.PZSELL if up else BSPType.PZBUY
        pzbcs.append(_bsp(units, k, kind, raws,
                          "%s盘整背驰(后%s%s柱面积更小)" % (
                              "上涨" if up else "下跌", unit_name,
                              "红" if up else "绿"), ratio,
                          level=level, src_raw_start=units[k].raw_start))

    # ---- 第二类: 一类点后第一次回抽不破前极值 (买卖点定律一) ----
    for k, up in first_idx.items():
        pull = _second_point_index(units, k)
        if pull is None:
            continue
        if not up and units[pull].end_value > units[k].end_value:
            bsps.append(_bsp(units, pull, BSPType.BUY2, raws,
                             "一买后首次回抽不破前低", level=level))
        elif up and units[pull].end_value < units[k].end_value:
            bsps.append(_bsp(units, pull, BSPType.SELL2, raws,
                             "一卖后首次反抽不破前高", level=level))

    # ---- 第三类: 离开中枢后回抽不回中枢 (中枢定理三) ----
    for zs in zhongshus:
        third = _third_point_after_zhongshu(units, zs)
        if third is None:
            continue
        pull, kind, reason, ref_zs = third
        bsps.append(_bsp(units, pull, kind, raws, reason, ref_zs=ref_zs,
                         level=level))

    bsps.sort(key=lambda b: b.raw_idx)
    pzbcs.sort(key=lambda b: b.raw_idx)
    return bsps, pzbcs


def find_buy_sell_points(units: List, zhongshus: List[ZhongShu],
                         macd: MacdHelper, raws: List[RawKLine],
                         beichi_ratio: float = 0.9) -> List[BuySellPoint]:
    """兼容入口: 只返回三类买卖点 (见 find_signals)。"""
    return find_signals(units, zhongshus, macd, raws, beichi_ratio)[0]
