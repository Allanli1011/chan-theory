# -*- coding: utf-8 -*-
"""
ChanAnalyzer —— 缠论分析主入口, 串起完整流水线。

原始K线 → 包含处理(合并K线) → 分型 → 笔 → 线段
        → 笔中枢 / 线段中枢 → MACD → 背驰与买卖点 → 走势类型

买卖点默认在【笔级别】给出 (以笔为走势单元、笔中枢为中枢), 颗粒度更细、更贴合
课24示例; 同时计算线段中枢供更高级别参考。多级别递归见 analyze_multi_level()。
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
from .models import RawKLine, TrendType
from .segment import build_segments
from .signals import classify_trend, find_buy_sell_points
from .zhongshu import find_zhongshus


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
        self.macd: Optional[MacdHelper] = None
        self.bsps = []
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
        self.macd = MacdHelper(self.close)
        self.bsps = find_buy_sell_points(self.bis, self.bi_zhongshus,
                                         self.macd, self.raws, self.beichi_ratio)
        self.trend = classify_trend(self.bi_zhongshus)
        return self

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
            "笔中枢         : %d" % len(self.bi_zhongshus),
            "线段中枢       : %d" % len(self.seg_zhongshus),
            "整体走势类型   : %s" % self.trend,
            "买卖点         : %d" % len(self.bsps),
            "-" * 40,
        ]
        for z in self.bi_zhongshus:
            lines.append("  中枢 ZD=%.2f ZG=%.2f (GG=%.2f DD=%.2f) 元素%d" % (
                z.ZD, z.ZG, z.GG, z.DD, len(z.elements)))
        lines.append("-" * 40)
        for b in self.bsps:
            lines.append("  %s @ %s  价=%.2f  %s%s" % (
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
