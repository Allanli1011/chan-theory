# -*- coding: utf-8 -*-
"""
线段的划分 —— 特征序列法 (课65/课67/课71/课78)。

线段: 至少三笔, 且前三笔必须有重叠 (课65)。用 S 记向上笔, X 记向下笔:
  * 以向上笔开始的线段  S1X1S2X2…  其"特征序列"取反向笔  X1X2…, 只考察【顶分型】;
  * 以向下笔开始的线段  X1S1X2S2…  其特征序列取  S1S2…,        只考察【底分型】。
特征序列相邻元素无重合区间 => 一个"缺口"(课67)。特征序列须先做非包含处理 => 标准特征序列。

线段终结 (课67 两种情况):
  第一种(无缺口): 顶/底分型中第一、第二元素之间【无缺口】 -> 线段在该分型极值处结束;
  第二种(有缺口): 第一、第二元素之间【有缺口】 -> 仅当从极值起反向笔序列的特征序列
                  出现【反向分型】时, 线段才在该极值处结束 (后序列分型不分两种情况)。

参考 课65"线段被笔破坏"定义: 向上线段序列 d1g1d2g2…, 若存在 j>=i+2 使 dj<=gi 则被破坏,
本实现以课67的特征序列法为准 (二者在多数情形等价, 课67为可操作的精确标准)。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .models import Bi, Direction, Segment


# --------------------------------------------------------------------------- #
# 特征序列处理工具
# --------------------------------------------------------------------------- #
def _standardize(feats: List[tuple], seg_dir: Direction) -> List[Dict]:
    """对特征序列元素做非包含处理 (课65 顺序原则)。

    feats: [(orig_bi_idx, low, high), ...] (反向笔, 按时间顺序)
    向上线段(找顶分型) -> 向上合并(高高: high=max, low=max);
    向下线段(找底分型) -> 向下合并(低低: high=min, low=min)。
    每个标准元素记录贡献极值的原始笔下标 key (用于回溯线段终点)。
    """
    up = seg_dir is Direction.UP
    std: List[Dict] = []
    for oi, lo, hi in feats:
        if not std:
            std.append({"low": lo, "high": hi, "key": oi})
            continue
        last = std[-1]
        included = (last["high"] >= hi and last["low"] <= lo) or \
                   (hi >= last["high"] and lo <= last["low"])
        if included:
            if up:
                nh, nl = max(last["high"], hi), max(last["low"], lo)
                key = last["key"] if last["high"] >= hi else oi
            else:
                nh, nl = min(last["high"], hi), min(last["low"], lo)
                key = last["key"] if last["low"] <= lo else oi
            last["high"], last["low"], last["key"] = nh, nl, key
        else:
            std.append({"low": lo, "high": hi, "key": oi})
    return std


def _is_fractal(std: List[Dict], t: int, seg_dir: Direction) -> bool:
    """std[t] 是否为终结分型(向上线段看顶分型, 向下看底分型)。"""
    if t <= 0 or t >= len(std) - 1:
        return False
    a, b, c = std[t - 1], std[t], std[t + 1]
    if seg_dir is Direction.UP:   # 顶分型
        return (b["high"] > a["high"] and b["high"] > c["high"]
                and b["low"] > a["low"] and b["low"] > c["low"])
    return (b["high"] < a["high"] and b["high"] < c["high"]      # 底分型
            and b["low"] < a["low"] and b["low"] < c["low"])


def _terminal_fractal(std: List[Dict], seg_dir: Direction) -> Optional[int]:
    """在标准特征序列中找首个终结分型, 返回其峰/谷元素下标。"""
    for t in range(1, len(std) - 1):
        if _is_fractal(std, t, seg_dir):
            return t
    return None


def _confirm_case2(bis: List[Bi], peak_bi: int, seg_dir: Direction) -> bool:
    """课67 第二种情况确认 (有界扫描):
    自极值笔之后逐笔考察 ——
      * 若先出现【同向新极值】(向上线段又创新高/向下又创新低) => 该分型作废, 线段延续;
      * 若在此之前, 反向线段的特征序列出现【反向分型】 => 确认线段在此结束。
    """
    nd = seg_dir.opposite
    peak_high = bis[peak_bi].high
    peak_low = bis[peak_bi].low
    feats: List[tuple] = []
    for j in range(peak_bi + 1, len(bis)):
        if seg_dir is Direction.UP and bis[j].high > peak_high:
            return False
        if seg_dir is Direction.DOWN and bis[j].low < peak_low:
            return False
        if bis[j].direction is seg_dir:        # 反向线段的特征元素 = 原方向笔
            feats.append((j, bis[j].low, bis[j].high))
            std = _standardize(feats, nd)
            if _terminal_fractal(std, nd) is not None:
                return True
    return False


def _has_gap(first: Dict, second: Dict, seg_dir: Direction) -> bool:
    """分型第一(左)、第二(峰)元素之间是否有缺口(无重合)。"""
    if seg_dir is Direction.UP:
        return first["high"] < second["low"]
    return first["low"] > second["high"]


def _find_break(bis: List[Bi], start: int, seg_dir: Direction) -> Optional[int]:
    """返回该线段最后一笔的下标(终结笔); 未被破坏则 None。

    扫描标准特征序列中的分型, 取首个【可确认】者作为线段终结 (课67):
      * 第一种情况(第一、二元素无缺口): 直接确认;
      * 第二种情况(有缺口): 由 _confirm_case2 有界确认 (先创新极值则作废, 继续看后面)。
    """
    feats = [(j, bis[j].low, bis[j].high)
             for j in range(start + 1, len(bis)) if bis[j].direction is not seg_dir]
    if len(feats) < 3:
        return None
    std = _standardize(feats, seg_dir)
    for t in range(1, len(std) - 1):
        if not _is_fractal(std, t, seg_dir):
            continue
        peak_bi = std[t]["key"]          # 峰/谷处的反向笔下标
        seg_end = peak_bi - 1            # 该方向笔, 即线段终点笔
        if seg_end < start + 2:          # 线段至少三笔
            continue
        if not _has_gap(std[t - 1], std[t], seg_dir):
            return seg_end               # 第一种情况: 无缺口, 直接确认
        if _confirm_case2(bis, peak_bi, seg_dir):
            return seg_end               # 第二种情况: 有界反向分型确认
        # 否则该分型未确认, 继续扫描后面更晚的分型
    return None


def build_segments(bis: List[Bi]) -> List[Segment]:
    """将笔序列唯一地划分为线段的连接。"""
    segs: List[Segment] = []
    n = len(bis)
    start = 0
    while start + 2 < n:
        d = bis[start].direction
        end = _find_break(bis, start, d)
        if end is None:
            break
        segs.append(Segment(direction=d, bis=bis[start:end + 1],
                            idx=len(segs), completed=True))
        start = end + 1
    # 末段(可能未完成)线段, 保留以表达当下走势方向
    if start < n:
        rem = bis[start:]
        if rem:
            segs.append(Segment(direction=rem[0].direction, bis=rem,
                                idx=len(segs), completed=False))
    return segs
