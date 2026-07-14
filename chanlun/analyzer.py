# -*- coding: utf-8 -*-
"""
ChanAnalyzer —— 缠论分析主入口, 串起完整流水线。

原始K线 → 包含处理(合并K线) → 分型 → 笔 → 线段
        → 笔中枢 / 线段中枢 (含扩展/升级) → MACD → 背驰与买卖点 → 走势类型

买卖点在【笔级别】与【线段级别】分别给出 (bsps/seg_bsps), 盘整背驰单独存放
(pzbcs/seg_pzbcs)。多级别递归见 analyze_multi_level(), 区间套定位见
interval_nest() 与 ChanAnalyzer.nest_bi_in_seg()。
"""
from __future__ import annotations

from typing import List, Optional, Union

import numpy as np
import pandas as pd

from .bi import build_bis
from .cmerge import merge_klines
from .data import from_dataframe
from .fractal import find_fractals
from .macd import MacdHelper
from .models import BSPType, BuySellPoint, RawKLine, TrendType
from .segment import build_segments
from .signals import classify_trend, find_buy_sell_points, find_signals
from .zhongshu import find_expansions, find_zhongshus

# 背驰类信号 (可作区间套链条节点, 课27)
_BEICHI_TYPES = {BSPType.BUY1, BSPType.SELL1, BSPType.PZBUY, BSPType.PZSELL}


class ChanAnalyzer:
    def __init__(self, data: Union[List[RawKLine], pd.DataFrame],
                 beichi_ratio: float = 0.9, bi_min_dist: int = 4,
                 zhongshu_mode: str = "extension"):
        if isinstance(data, pd.DataFrame):
            self.raws: List[RawKLine] = from_dataframe(data)
        else:
            self.raws = list(data)
        self.beichi_ratio = beichi_ratio
        self.bi_min_dist = bi_min_dist
        self.zhongshu_mode = zhongshu_mode
        self.close = np.array([r.close for r in self.raws], dtype=float)
        # 结果占位
        self.merged = []
        self.fractals = []
        self.bis = []
        self.segments = []
        self.bi_zhongshus = []
        self.seg_zhongshus = []
        self.bi_zs_expansions = []
        self.seg_zs_expansions = []
        self.macd: Optional[MacdHelper] = None
        self.bsps = []
        self.pzbcs = []
        self.seg_bsps = []
        self.seg_pzbcs = []
        self.trend = TrendType.CONSOLIDATION

    def run(self) -> "ChanAnalyzer":
        self.merged = merge_klines(self.raws)
        self.fractals = find_fractals(self.merged, self.raws)
        self.bis = build_bis(self.fractals, self.merged, self.raws, self.bi_min_dist)
        self.segments = build_segments(self.bis)
        self.bi_zhongshus = find_zhongshus(
            self.bis, level="bi", mode=self.zhongshu_mode)
        completed_segments = [s for s in self.segments if s.completed]
        self.seg_zhongshus = find_zhongshus(
            completed_segments, level="seg", mode=self.zhongshu_mode)
        # 中枢扩展 (课29/36): 相邻重叠中枢合并为更高一级中枢
        self.bi_zs_expansions = find_expansions(self.bi_zhongshus, level="bi")
        self.seg_zs_expansions = find_expansions(self.seg_zhongshus, level="seg")
        self.macd = MacdHelper(self.close)
        # 笔级别信号 (一/二/三类买卖点 + 盘整背驰)
        self.bsps, self.pzbcs = find_signals(
            self.bis, self.bi_zhongshus, self.macd, self.raws,
            self.beichi_ratio, level="bi")
        # 线段级别信号 (以线段为走势单元、线段中枢为中枢)
        self.seg_bsps, self.seg_pzbcs = find_signals(
            completed_segments, self.seg_zhongshus, self.macd, self.raws,
            self.beichi_ratio, level="seg")
        self.trend = classify_trend(self.bi_zhongshus)
        return self

    # ------------------------------------------------------------------ #
    def nest_bi_in_seg(self) -> List[tuple]:
        """级内区间套 (课27): 在线段级背驰段内寻找笔级背驰点精确定位。

        返回 [(线段级背驰信号, 笔级精确化信号或 None), ...]。
        """
        out = []
        for sb in self.seg_bsps + self.seg_pzbcs:
            if sb.bsp_type not in _BEICHI_TYPES or sb.src_raw_start is None:
                out_bsp = None
            else:
                out_bsp = _pick_nested(sb.src_raw_start, sb.raw_idx,
                                       sb.bsp_type.is_buy,
                                       self.bsps + self.pzbcs)
            out.append((sb, out_bsp))
        return out

    # ------------------------------------------------------------------ #
    def summary(self) -> str:
        lines = [
            "缠论分析摘要",
            "=" * 40,
            "原始K线        : %d" % len(self.raws),
            "合并K线        : %d" % len(self.merged),
            "分型           : %d (顶 %d / 底 %d)" % (
                len(self.fractals),
                sum(1 for f in self.fractals if f.kind.value == 1),
                sum(1 for f in self.fractals if f.kind.value == -1)),
            "笔             : %d" % len(self.bis),
            "线段           : %d" % len(self.segments),
            "笔中枢         : %d (9段升级 %d, 扩展 %d)" % (
                len(self.bi_zhongshus),
                sum(1 for z in self.bi_zhongshus if z.upgraded),
                len(self.bi_zs_expansions)),
            "线段中枢       : %d (9段升级 %d, 扩展 %d)" % (
                len(self.seg_zhongshus),
                sum(1 for z in self.seg_zhongshus if z.upgraded),
                len(self.seg_zs_expansions)),
            "整体走势类型   : %s" % self.trend,
            "笔级买卖点     : %d (另盘整背驰 %d)" % (len(self.bsps), len(self.pzbcs)),
            "线段级买卖点   : %d (另盘整背驰 %d)" % (
                len(self.seg_bsps), len(self.seg_pzbcs)),
            "-" * 40,
        ]
        for z in self.bi_zhongshus:
            tag = " ↑9段升级" if z.upgraded else ""
            lines.append("  中枢 ZD=%.2f ZG=%.2f (GG=%.2f DD=%.2f) 元素%d%s" % (
                z.ZD, z.ZG, z.GG, z.DD, len(z.elements), tag))
        lines.append("-" * 40)
        for b in self.bsps + self.pzbcs:
            lines.append("  [%s] %s @ %s  价=%.2f  %s%s" % (
                "笔" if b.level == "bi" else "段", b.bsp_type,
                str(b.dt)[:10], b.price, b.reason,
                "" if b.beichi_ratio is None else " (力度比%.2f)" % b.beichi_ratio))
        for b in self.seg_bsps + self.seg_pzbcs:
            lines.append("  [段] %s @ %s  价=%.2f  %s%s" % (
                b.bsp_type, str(b.dt)[:10], b.price, b.reason,
                "" if b.beichi_ratio is None else " (力度比%.2f)" % b.beichi_ratio))
        return "\n".join(lines)


# ---------------------------------------------------------------------------- #
# 多级别递归 (课17: 级别递归体系)
# ---------------------------------------------------------------------------- #
def resample(df: pd.DataFrame, rule: str, dt_col: str = "date") -> pd.DataFrame:
    """将K线重采样到更高级别 (如 '5min'->'30min', 'D'->'W')。"""
    d = df.copy()
    d[dt_col] = pd.to_datetime(d[dt_col])
    d = d.set_index(dt_col)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in d.columns:
        agg["volume"] = "sum"
    out = d.resample(rule).agg(agg).dropna().reset_index()
    return out


def analyze_multi_level(df: pd.DataFrame, levels: dict, **kwargs) -> dict:
    """对多个级别分别分析。levels: {名称: 重采样规则}, 规则为 None 表示原级别。

    例: analyze_multi_level(df_30min, {"30分钟": None, "日线": "D", "周线": "W"})
    返回 {名称: ChanAnalyzer}。
    """
    result = {}
    for name, rule in levels.items():
        sub = df if rule is None else resample(df, rule)
        result[name] = ChanAnalyzer(sub, **kwargs).run()
    return result


# ---------------------------------------------------------------------------- #
# 区间套定位 (课27/课61)
# ---------------------------------------------------------------------------- #
def _pick_nested(lo_raw: int, hi_raw: int, want_buy: bool,
                 candidates: List[BuySellPoint]) -> Optional[BuySellPoint]:
    """在原始K线下标区间 [lo_raw, hi_raw] 内选取同方向的最晚背驰信号。"""
    picked = None
    for b in candidates:
        if b.bsp_type not in _BEICHI_TYPES or b.bsp_type.is_buy != want_buy:
            continue
        if not (lo_raw <= b.raw_idx <= hi_raw):
            continue
        if picked is None or b.raw_idx > picked.raw_idx:
            picked = b
    return picked


def nest_refine(coarse: "ChanAnalyzer", fine: "ChanAnalyzer",
                bsp: BuySellPoint) -> Optional[BuySellPoint]:
    """区间套单步 (课27): 在粗级别背驰段的时间区间内找细级别背驰点。

    粗级别背驰段 = [src_raw_start, raw_idx] 对应的时间范围。用
    (上一根粗K线的时间戳, raw_idx 那根粗K线的时间戳] 表示该范围: pandas
    resample('W'/'ME'等) 默认按【右边界】给bar打标签(一周的标签是该周最后
    一天), 而未重采样的原始K线时间戳天然是"该K线自身"的时间点, 两者都满足
    "bar i 覆盖 (label[i-1], label[i]]" —— 用该统一写法避免按左边界处理
    右标签数据时把区间套误判为覆盖了错误的粗K线范围。
    细级别候选 = 同方向的一类点或盘整背驰点, 取最晚者。
    """
    if bsp.src_raw_start is None or not coarse.raws or not fine.raws:
        return None
    lo_i = bsp.src_raw_start - 1
    t0 = pd.Timestamp(coarse.raws[lo_i].dt) if lo_i >= 0 else None
    t1 = pd.Timestamp(coarse.raws[bsp.raw_idx].dt)
    want_buy = bsp.bsp_type.is_buy
    picked = None
    for b in fine.bsps + fine.pzbcs:
        if b.bsp_type not in _BEICHI_TYPES or b.bsp_type.is_buy != want_buy:
            continue
        if b.src_raw_start is None:
            continue
        dtb = pd.Timestamp(fine.raws[b.raw_idx].dt)
        if (t0 is not None and dtb <= t0) or dtb > t1:
            continue
        if picked is None or b.raw_idx > picked.raw_idx:
            picked = b
    return picked


def interval_nest(df: pd.DataFrame, levels: dict, **kwargs) -> list:
    """区间套定位 (课27): 从最粗级别的背驰点逐级向细精确化。

    levels: {名称: 重采样规则}, 按【从细到粗】排列, 规则 None 表示原级别。
    例: interval_nest(df_daily, {"日线": None, "周线": "W", "月线": "ME"})
    返回 [{"level": 最粗级别名, "bsp": 背驰点, "chain": [(级别, bsp), ...]}],
    chain 自粗到细, 每级 bsp 的时间都落在上一级背驰段的时间区间内。
    """
    d = df.copy()
    cols = {c.lower(): c for c in d.columns}
    dt_col = next((cols[n] for n in ("date", "datetime", "time", "trade_date")
                   if n in cols), d.columns[0])
    d[dt_col] = pd.to_datetime(d[dt_col])
    analyzers = {name: ChanAnalyzer(
                     d if rule is None else resample(d, rule, dt_col=dt_col),
                     **kwargs).run()
                 for name, rule in levels.items()}
    names = list(levels.keys())          # 从细到粗
    coarsest = names[-1]
    out = []
    for bsp in analyzers[coarsest].bsps + analyzers[coarsest].pzbcs:
        if bsp.bsp_type not in _BEICHI_TYPES:
            continue
        chain = [(coarsest, bsp)]
        cur = bsp
        for k in range(len(names) - 1, 0, -1):
            refined = nest_refine(analyzers[names[k]], analyzers[names[k - 1]], cur)
            if refined is None:
                break
            chain.append((names[k - 1], refined))
            cur = refined
        out.append({"level": coarsest, "bsp": bsp, "chain": chain})
    return out
