# -*- coding: utf-8 -*-
"""
走势中枢的识别 (课17/课18/课29)。

定义 (课17): 某级别走势类型中, 被至少三个连续次级别走势类型所重叠的部分。
精确计算 (课18): 连续三个次级别走势 A、B、C, 高低点 (a1,a2)(b1,b2)(c1,c2),
    中枢区间 = ( ZD , ZG ) = ( max(a2,b2,c2) , min(a1,b1,c1) )
    即 ZG = min(三者高点)  ZD = max(三者低点), 需 ZG > ZD。
另记 GG = max(各元素高点), DD = min(各元素低点)。

中枢维持/破坏 (课18 中枢定理三): 某中枢的破坏 <=> 一个次级别走势离开中枢后,
其后的次级别回抽不再重新回到中枢区间 [ZD, ZG] 内。

级别升级两途径:
  * 延伸升级 (课33): "中枢的延伸不能超过5段, 一旦出现6段的延伸, 加上形成中枢
    本身那三段, 就构成更大级别的中枢了" —— 即元素达 9 段, 标记 upgraded;
  * 中枢扩展 (课29/36): 两个都已走出来的相邻同级别中枢, 区间 [ZD,ZG] 相互重叠
    (即不满足趋势排列), 合并为更高一级中枢 —— 见 find_expansions。

本实现对"次级别走势"既支持笔(笔中枢), 也支持线段(线段中枢)。
"""
from __future__ import annotations

from typing import List, Sequence

from .models import Direction, ZhongShu


def find_zhongshus(units: Sequence, level: str = "bi",
                   mode: str = "extension") -> List[ZhongShu]:
    """从走势单元序列(笔或线段)中识别一系列中枢。

    采用"公共重叠"判据 (课17"被至少三个连续次级别走势所重叠的部分"):
      * 首个三连笔/线段若存在公共重叠区间 [ZD, ZG] 即确立一个中枢;
      * 之后逐个纳入后续单元, 只要纳入后【所有成员仍存在公共重叠】(running overlap)
        即延伸中枢(盘整延伸); 一旦某单元使公共重叠为空, 说明走势已离开, 中枢在此结束。
    这样趋势笔不会被错误吞入, 一段趋势会被自然切分为多个依次升/降的中枢, 进而可识别趋势背驰。
    ZG=min(成员高点) ZD=max(成员低点) GG=max(成员高点) DD=min(成员低点)。
    mode:
      * extension: 公共重叠持续存在时延伸当前中枢;
      * same_level: 同级别分解视角, 只用首个三段重叠定义一个中枢,
        不把后续重叠段继续吞入该中枢。
    """
    if mode not in {"extension", "same_level"}:
        raise ValueError("mode must be 'extension' or 'same_level'")

    zss: List[ZhongShu] = []
    n = len(units)
    i = 0
    while i + 2 < n:
        zg = min(units[i].high, units[i + 1].high, units[i + 2].high)
        zd = max(units[i].low, units[i + 1].low, units[i + 2].low)
        if zg > zd:
            elems = [units[i], units[i + 1], units[i + 2]]
            gg = max(u.high for u in elems)
            dd = min(u.low for u in elems)
            j = i + 3
            while mode == "extension" and j < n:
                nzg = min(zg, units[j].high)
                nzd = max(zd, units[j].low)
                if nzg > nzd:                 # 纳入后仍有公共重叠 -> 延伸
                    zg, zd = nzg, nzd
                    elems.append(units[j])
                    gg = max(gg, units[j].high)
                    dd = min(dd, units[j].low)
                    j += 1
                else:
                    break
            zss.append(ZhongShu(
                elements=list(elems), ZG=zg, ZD=zd, GG=gg, DD=dd,
                direction=elems[0].direction,
                raw_start=elems[0].raw_start, raw_end=elems[-1].raw_end,
                level=level, idx=len(zss),
                upgraded=len(elems) >= 9,   # 3段成枢+延伸6段 => 更大级别 (课33)
            ))
            i = j  # 从离开中枢的单元继续搜索下一中枢
        else:
            i += 1
    return zss


def find_expansions(zss: List[ZhongShu], level: str = "bi") -> List[ZhongShu]:
    """中枢扩展 (课29/36): 相邻同级别中枢合并为更高一级中枢。

    课36: "中枢扩展的定义是在两个中枢都完全走出来的情况下定义的";
    课29 给出最弱情形: 背驰后的反弹仅触及前中枢 DD, 即把该中枢"变成一个级别上
    的扩展"。本实现取可操作判据: 相邻两个中枢的区间 [ZD,ZG] 相互重叠
    (即不满足趋势排列), 则发生扩展; 新中枢区间按课18公式作用于成员的波动区间:
        ZG* = min(各成员 GG)   ZD* = max(各成员 DD)
    连续重叠的中枢链会被吞入同一个扩展中枢 (须保持 ZG* > ZD*)。
    返回的扩展中枢 elements 为成员中枢列表, expanded=True, 级别高于成员一级。
    """
    out: List[ZhongShu] = []
    n = len(zss)
    i = 0
    while i + 1 < n:
        a, b = zss[i], zss[i + 1]
        overlap = b.ZD <= a.ZG and a.ZD <= b.ZG
        zg, zd = min(a.GG, b.GG), max(a.DD, b.DD)
        if not overlap or zg <= zd:
            i += 1
            continue
        members = [a, b]
        gg, dd = max(a.GG, b.GG), min(a.DD, b.DD)
        j = i + 2
        while j < n:
            c = zss[j]
            chain = c.ZD <= members[-1].ZG and members[-1].ZD <= c.ZG
            nzg, nzd = min(zg, c.GG), max(zd, c.DD)
            if not (chain and nzg > nzd):
                break
            members.append(c)
            zg, zd = nzg, nzd
            gg, dd = max(gg, c.GG), min(dd, c.DD)
            j += 1
        out.append(ZhongShu(
            elements=members, ZG=zg, ZD=zd, GG=gg, DD=dd,
            direction=members[0].direction,
            raw_start=members[0].raw_start, raw_end=members[-1].raw_end,
            level=level, idx=len(out), expanded=True,
        ))
        i = j
    return out
