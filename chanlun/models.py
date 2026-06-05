# -*- coding: utf-8 -*-
"""
缠论核心数据结构 (data models)。

层级关系:
    RawKLine(原始K线)
      └─ 包含处理 ─> KLine(合并K线)
            └─ 分型 ─> Fractal(顶/底分型)
                  └─ 连接 ─> Bi(笔)
                        └─ 划分 ─> Segment(线段)
                              └─ 重叠 ─> ZhongShu(走势中枢)
                                    └─ 判定 ─> BuySellPoint(买卖点)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Direction(Enum):
    """方向。"""
    UP = 1      # 向上
    DOWN = -1   # 向下

    @property
    def opposite(self) -> "Direction":
        return Direction.DOWN if self is Direction.UP else Direction.UP

    def __str__(self) -> str:
        return "向上" if self is Direction.UP else "向下"


class FractalType(Enum):
    """分型类型 (课17/课62)。"""
    TOP = 1      # 顶分型
    BOTTOM = -1  # 底分型

    def __str__(self) -> str:
        return "顶分型" if self is FractalType.TOP else "底分型"


class TrendType(Enum):
    """走势类型 (课17《走势分类》)。

    缠论将任意级别走势严格分为三类: 上涨、下跌、盘整。
    上涨/下跌统称"趋势", 趋势至少包含两个同级别中枢且中枢依次升高/降低;
    盘整则只包含一个中枢。
    """
    UP = 1            # 上涨 (趋势)
    DOWN = -1         # 下跌 (趋势)
    CONSOLIDATION = 0  # 盘整

    def __str__(self) -> str:
        return {TrendType.UP: "上涨", TrendType.DOWN: "下跌",
                TrendType.CONSOLIDATION: "盘整"}[self]


class BSPType(Enum):
    """买卖点类型 (课17等)。缠论只有三类买卖点。"""
    BUY1 = "一买"
    BUY2 = "二买"
    BUY3 = "三买"
    SELL1 = "一卖"
    SELL2 = "二卖"
    SELL3 = "三卖"

    @property
    def is_buy(self) -> bool:
        return self.value.endswith("买")

    def __str__(self) -> str:
        return self.value


# --------------------------------------------------------------------------- #
# 原始 / 合并 K线
# --------------------------------------------------------------------------- #
@dataclass
class RawKLine:
    """原始K线 (未经处理)。idx 为其在原始序列中的位置。"""
    idx: int
    dt: object          # datetime 或可比较的时间标签
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class KLine:
    """合并(包含处理后)的K线 —— 缠论分析的基本单元 (课17/课62)。

    一根合并K线可能由多根原始K线包含合并而成。high/low 为合并后的上下沿;
    elements 记录其覆盖的原始K线下标 (用于回溯 MACD 面积、绘图等)。
    """
    idx: int                       # 在合并序列中的位置
    high: float
    low: float
    elements: List[int]            # 覆盖的原始K线 idx 列表 (已排序)
    direction: Optional[Direction] = None  # 合并时所处的方向 (向上取高高, 向下取低低)

    @property
    def raw_begin(self) -> int:
        return self.elements[0]

    @property
    def raw_end(self) -> int:
        return self.elements[-1]


# --------------------------------------------------------------------------- #
# 分型 / 笔 / 线段
# --------------------------------------------------------------------------- #
@dataclass
class Fractal:
    """分型: 由相邻三根合并K线构成 (课17/课62)。

    顶分型: 中间K线的高、低点均为三者最高;
    底分型: 中间K线的高、低点均为三者最低。
    m_idx 指向中间(极值)那根合并K线。
    """
    kind: FractalType
    m_idx: int           # 中心(极值)合并K线的 idx
    high: float          # 中心K线的 high
    low: float           # 中心K线的 low
    left_idx: int        # 左侧合并K线 idx
    right_idx: int       # 右侧合并K线 idx
    raw_idx: int         # 极值对应的原始K线 idx (绘图用)
    dt: object = None    # 极值对应时间

    @property
    def value(self) -> float:
        """分型的极值价: 顶分型取 high, 底分型取 low。"""
        return self.high if self.kind is FractalType.TOP else self.low


@dataclass
class Bi:
    """笔: 连接相邻的一顶一底分型 (课62/课65)。"""
    direction: Direction
    fx_a: Fractal              # 起点分型
    fx_b: Fractal              # 终点分型
    m_start: int               # 起点合并K线 idx
    m_end: int                 # 终点合并K线 idx
    raw_start: int             # 起点原始K线 idx (MACD面积、绘图)
    raw_end: int               # 终点原始K线 idx
    idx: int = -1              # 在笔序列中的位置

    @property
    def high(self) -> float:
        return max(self.fx_a.value, self.fx_b.value)

    @property
    def low(self) -> float:
        return min(self.fx_a.value, self.fx_b.value)

    @property
    def start_value(self) -> float:
        return self.fx_a.value

    @property
    def end_value(self) -> float:
        return self.fx_b.value


@dataclass
class Segment:
    """线段: 至少由三笔构成且有重叠, 通过特征序列划分 (课65/课67)。"""
    direction: Direction
    bis: List[Bi]
    idx: int = -1
    completed: bool = True

    @property
    def start_bi(self) -> Bi:
        return self.bis[0]

    @property
    def end_bi(self) -> Bi:
        return self.bis[-1]

    @property
    def raw_start(self) -> int:
        return self.bis[0].raw_start

    @property
    def raw_end(self) -> int:
        return self.bis[-1].raw_end

    @property
    def start_value(self) -> float:
        return self.bis[0].fx_a.value

    @property
    def end_value(self) -> float:
        return self.bis[-1].fx_b.value

    @property
    def high(self) -> float:
        return max(b.high for b in self.bis)

    @property
    def low(self) -> float:
        return min(b.low for b in self.bis)


# --------------------------------------------------------------------------- #
# 走势中枢
# --------------------------------------------------------------------------- #
@dataclass
class ZhongShu:
    """走势中枢: 至少三个连续次级别走势(笔/线段)的重叠区间 (课17/课18/课29)。

        ZG = min(各元素高点)   中枢上沿
        ZD = max(各元素低点)   中枢下沿
        GG = max(各元素高点)   中枢区间最高
        DD = min(各元素低点)   中枢区间最低
    要求 ZG > ZD (存在重叠) 方成立。
    """
    elements: List[object]     # 构成中枢的笔或线段 (按时间顺序)
    ZG: float
    ZD: float
    GG: float
    DD: float
    direction: Direction       # 进入中枢的方向 (决定其在走势中的角色)
    raw_start: int
    raw_end: int
    level: str = "bi"          # 'bi'(笔中枢) 或 'seg'(线段中枢)
    idx: int = -1

    @property
    def mid(self) -> float:
        return (self.ZG + self.ZD) / 2.0

    def contains(self, price: float) -> bool:
        return self.ZD <= price <= self.ZG


# --------------------------------------------------------------------------- #
# 买卖点
# --------------------------------------------------------------------------- #
@dataclass
class BuySellPoint:
    """买卖点 (课17等)。"""
    bsp_type: BSPType
    raw_idx: int               # 对应原始K线 idx
    dt: object
    price: float
    reason: str = ""           # 触发说明 (背驰/中枢突破回抽等)
    beichi_ratio: Optional[float] = None  # 背驰力度比 (MACD面积之比), 若适用
    ref_zs_idx: Optional[int] = None
    ref_zs_zd: Optional[float] = None
    ref_zs_zg: Optional[float] = None
    ref_zs_raw_start: Optional[int] = None
    ref_zs_raw_end: Optional[int] = None
