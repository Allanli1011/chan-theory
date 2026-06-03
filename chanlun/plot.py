# -*- coding: utf-8 -*-
"""
缠论分析结果可视化 (mplfinance + matplotlib)。

在K线图上叠加: 笔(细线)、线段(粗线)、走势中枢(矩形)、三类买卖点(标注);
下方副图绘制 MACD (DIF/DEA 黄白线 + 红绿柱), 用于背驰判断。
"""
from __future__ import annotations

from typing import Optional

import matplotlib
import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from .models import BSPType, Direction

# 中文字体: 给出回退链, 取系统中实际可用者 (Windows 常见 YaHei/SimHei)
_CJK_FONTS = ["Microsoft YaHei", "SimHei", "SimSun", "DengXian", "DejaVu Sans"]


def _pick_cjk_fonts():
    try:
        from matplotlib import font_manager
        have = {f.name for f in font_manager.fontManager.ttflist}
        ordered = [f for f in _CJK_FONTS if f in have]
        return ordered or _CJK_FONTS
    except Exception:  # noqa: BLE001
        return _CJK_FONTS


_FONTS = _pick_cjk_fonts()
matplotlib.rcParams["font.sans-serif"] = _FONTS
matplotlib.rcParams["axes.unicode_minus"] = False

_BSP_STYLE = {
    BSPType.BUY1: ("1B", "red", -1), BSPType.BUY2: ("2B", "orangered", -1),
    BSPType.BUY3: ("3B", "darkorange", -1),
    BSPType.SELL1: ("1S", "green", 1), BSPType.SELL2: ("2S", "seagreen", 1),
    BSPType.SELL3: ("3S", "darkgreen", 1),
}


def plot_analysis(ana, start: int = 0, end: Optional[int] = None,
                  save_path: Optional[str] = None, show: bool = False,
                  title: str = "缠论分析", figscale: float = 1.6):
    """绘制缠论分析图。start/end 为原始K线下标窗口(默认全图)。"""
    raws = ana.raws
    if ana.macd is None:
        raise ValueError("analysis must be run before plotting")
    n = len(raws)
    end = n if end is None else end
    start = max(0, start)
    end = min(n, end)
    if start >= end:
        raise ValueError("empty plot window")
    sub = raws[start:end]

    df = pd.DataFrame({
        "Open": [r.open for r in sub], "High": [r.high for r in sub],
        "Low": [r.low for r in sub], "Close": [r.close for r in sub],
        "Volume": [r.volume for r in sub],
    }, index=pd.to_datetime([r.dt for r in sub]))

    # MACD 副图
    dif = ana.macd.dif[start:end]
    dea = ana.macd.dea[start:end]
    hist = ana.macd.macd[start:end]
    hist_colors = ["red" if h >= 0 else "green" for h in hist]
    aps = [
        mpf.make_addplot(dif, panel=1, color="white", width=0.8, ylabel="MACD"),
        mpf.make_addplot(dea, panel=1, color="yellow", width=0.8),
        mpf.make_addplot(hist, panel=1, type="bar", color=hist_colors, width=0.7),
    ]

    mc = mpf.make_marketcolors(up="red", down="green", edge="inherit",
                               wick="inherit", volume="in")
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc,
                               facecolor="#101010", gridcolor="#303030",
                               rc={"font.sans-serif": _FONTS,
                                   "axes.unicode_minus": False})
    fig, axes = mpf.plot(df, type="candle", style=style, addplot=aps,
                         volume=False, returnfig=True, figscale=figscale,
                         panel_ratios=(3, 1), datetime_format="%y-%m",
                         xrotation=0, tight_layout=True,
                         title=title, warn_too_much_data=10 ** 7)
    ax = axes[0]

    def pos(raw_idx):  # 原始下标 -> 子图横坐标
        return raw_idx - start

    def visible(raw_idx):
        return start <= raw_idx < end

    def visible_range(raw_start, raw_end):
        return raw_start < end and raw_end >= start

    # 笔: 连接相邻分型端点的折线
    if ana.bis:
        xs, ys = [], []
        pts = [(ana.bis[0].fx_a.raw_idx, ana.bis[0].fx_a.value)]
        for b in ana.bis:
            pts.append((b.fx_b.raw_idx, b.fx_b.value))
        for ri, val in pts:
            if visible(ri):
                xs.append(pos(ri)); ys.append(val)
        ax.plot(xs, ys, color="#33aaff", linewidth=0.9, alpha=0.9,
                label="笔", zorder=4)

    # 线段: 较粗折线
    if ana.segments:
        xs, ys = [], []
        pts = [(ana.segments[0].start_bi.fx_a.raw_idx, ana.segments[0].start_value)]
        for s in ana.segments:
            pts.append((s.end_bi.fx_b.raw_idx, s.end_value))
        for ri, val in pts:
            if visible(ri):
                xs.append(pos(ri)); ys.append(val)
        ax.plot(xs, ys, color="#ffcc00", linewidth=2.0, alpha=0.95,
                label="线段", zorder=5)

    # 中枢: [ZD, ZG] 矩形 (实线), [DD, GG] 振幅范围 (虚线框)
    for z in ana.bi_zhongshus:
        if not visible_range(z.raw_start, z.raw_end):
            continue
        x0 = pos(max(z.raw_start, start))
        x1 = pos(min(z.raw_end, end - 1))
        w = max(x1 - x0, 0.5)
        ax.add_patch(Rectangle((x0, z.ZD), w, z.ZG - z.ZD, fill=True,
                               facecolor="#ff990033", edgecolor="#ffaa00",
                               linewidth=1.2, zorder=3))

    # 买卖点标注
    for b in ana.bsps:
        if not visible(b.raw_idx):
            continue
        label, color, sign = _BSP_STYLE[b.bsp_type]
        x = pos(b.raw_idx)
        ax.scatter([x], [b.price], marker="o", s=28, color=color, zorder=6,
                   edgecolors="white", linewidths=0.5)
        ax.annotate(label, (x, b.price),
                    textcoords="offset points", xytext=(0, sign * 12),
                    ha="center", color=color, fontsize=9, fontweight="bold",
                    zorder=7)

    ax.legend(loc="upper left", fontsize=9, facecolor="#202020",
              labelcolor="white", framealpha=0.6)

    if save_path:
        fig.savefig(save_path, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    if show:
        plt.show()
    else:
        plt.close(fig)
    return save_path
