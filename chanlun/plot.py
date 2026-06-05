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

# 中文字体回退链 (跨平台): Windows / macOS / Linux(CI 用 apt 装 fonts-wqy-* 或 noto-cjk)
_CJK_FONTS = [
    "Microsoft YaHei", "SimHei", "SimSun", "DengXian",            # Windows
    "PingFang SC", "Hiragino Sans GB", "STHeiti", "Arial Unicode MS",  # macOS
    "WenQuanYi Zen Hei", "WenQuanYi Micro Hei",                   # Linux: fonts-wqy-*
    "Noto Sans CJK SC", "Noto Sans CJK JP", "Noto Sans CJK TC",   # Linux: fonts-noto-cjk
    "Noto Sans CJK", "Source Han Sans SC", "Droid Sans Fallback",
    "DejaVu Sans",                                                # 最后回退(无中文字形)
]
_CJK_FILE_TOKENS = ("wqy", "noto", "cjk", "hei", "song", "ming",
                    "han", "droidsansfallback", "yahei", "simsun")


def _pick_cjk_fonts():
    """返回系统中实际可用的中文字体回退链。

    先按字体名匹配; 若一个都没命中(常见于裸 Linux/CI), 则主动扫描系统字体文件,
    注册疑似中文字体并用其真实名称, 确保中文不会退化成豆腐块(□)。
    """
    try:
        from matplotlib import font_manager as fm
        have = {f.name for f in fm.fontManager.ttflist}
        ordered = [f for f in _CJK_FONTS if f in have]
        if ordered:
            return ordered + ["DejaVu Sans"]
        import os
        found = []
        for path in fm.findSystemFonts(fontext="ttf"):
            base = os.path.basename(path).lower()
            if any(tok in base for tok in _CJK_FILE_TOKENS):
                try:
                    fm.fontManager.addfont(path)
                    found.append(fm.FontProperties(fname=path).get_name())
                except Exception:  # noqa: BLE001
                    pass
        # 去重保序
        uniq = list(dict.fromkeys(found))
        return uniq + ["DejaVu Sans"] if uniq else _CJK_FONTS
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
    # DIF/DEA/柱单位相同(柱=2*(DIF-DEA)), 必须共用同一根 y 轴, 否则 mplfinance 的
    # secondary_y='auto' 会把 DIF、DEA 拆到不同刻度的两根轴上, 导致白黄线的视觉交叉
    # 与红绿柱翻色(真实 DIF=DEA 处)对不上。secondary_y=False 强制三者同轴。
    aps = [
        mpf.make_addplot(dif, panel=1, color="white", width=0.8, ylabel="MACD",
                         secondary_y=False),
        mpf.make_addplot(dea, panel=1, color="yellow", width=0.8, secondary_y=False),
        mpf.make_addplot(hist, panel=1, type="bar", color=hist_colors, width=0.7,
                         secondary_y=False),
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
        ax.annotate(f"ZS{z.idx}", (x0, z.ZG),
                    textcoords="offset points", xytext=(2, 2),
                    ha="left", va="bottom", color="#ffcc66", fontsize=8,
                    zorder=6)

    # 买卖点标注
    for b in ana.bsps:
        if not visible(b.raw_idx):
            continue
        label, color, sign = _BSP_STYLE[b.bsp_type]
        ref_idx = getattr(b, "ref_zs_idx", None)
        if ref_idx is not None:
            label = f"{label}\nZS{ref_idx}"
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
