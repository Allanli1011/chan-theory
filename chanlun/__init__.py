# -*- coding: utf-8 -*-
"""
chanlun —— 缠中说禅"缠论"技术分析框架的 Python 实现。

完整流水线 (《教你炒股票》系列课程):
    原始K线 → 包含处理 → 分型 → 笔 → 线段 → 走势中枢 → 走势类型 → 背驰 → 买卖点
并支持级别递归 (1分钟/5分钟/30分钟/日线/周线...)。

主入口: chanlun.analyzer.ChanAnalyzer
"""
from .models import (
    Direction,
    FractalType,
    TrendType,
    BSPType,
    RawKLine,
    KLine,
    Fractal,
    Bi,
    Segment,
    ZhongShu,
    BuySellPoint,
)
from .analyzer import ChanAnalyzer

__all__ = [
    "Direction",
    "FractalType",
    "TrendType",
    "BSPType",
    "RawKLine",
    "KLine",
    "Fractal",
    "Bi",
    "Segment",
    "ZhongShu",
    "BuySellPoint",
    "ChanAnalyzer",
]

__version__ = "0.1.0"
