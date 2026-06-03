# -*- coding: utf-8 -*-
"""
数据载入与样本生成。

缠论分析所需的输入是标准 OHLC K线序列。本模块提供:
  * from_dataframe / load_csv : 从 pandas / CSV 载入真实行情;
  * make_sample             : 生成带有明确"趋势-盘整-趋势"结构的合成数据, 便于演示与测试。

真实数据可由 akshare / tushare / baostock 等获取后, 整理为含
['date','open','high','low','close','volume'] 列的 DataFrame 传入。
"""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from .models import RawKLine


def from_dataframe(df: pd.DataFrame) -> List[RawKLine]:
    """将 DataFrame 转为 RawKLine 列表。

    需要的列 (不区分大小写): date/datetime, open, high, low, close, [volume]。
    """
    cols = {c.lower(): c for c in df.columns}

    def pick(*names):
        for n in names:
            if n in cols:
                return cols[n]
        raise KeyError("缺少列: %s (现有列: %s)" % (names, list(df.columns)))

    c_dt = pick("date", "datetime", "time", "trade_date")
    c_o = pick("open")
    c_h = pick("high")
    c_l = pick("low")
    c_c = pick("close")
    c_v = cols.get("volume", cols.get("vol"))

    if df.empty:
        return []

    sortable_dt = pd.to_datetime(df[c_dt], errors="coerce")
    if sortable_dt.notna().all() and not sortable_dt.is_monotonic_increasing:
        df = df.assign(_chan_dt_sort=sortable_dt).sort_values("_chan_dt_sort")
        df = df.drop(columns=["_chan_dt_sort"])

    out: List[RawKLine] = []
    for i, (_, row) in enumerate(df.iterrows()):
        o = float(row[c_o])
        h = float(row[c_h])
        l = float(row[c_l])
        c = float(row[c_c])
        if not np.all(np.isfinite([o, h, l, c])):
            raise ValueError("OHLC values must be finite")
        if h < l:
            raise ValueError("high must be greater than or equal to low")
        volume = 0.0
        if c_v:
            volume = 0.0 if pd.isna(row[c_v]) else float(row[c_v])
            if not np.isfinite(volume):
                raise ValueError("volume values must be finite")
        out.append(RawKLine(
            idx=i,
            dt=row[c_dt],
            open=o,
            high=h,
            low=l,
            close=c,
            volume=volume,
        ))
    return out


def load_csv(path: str, **kwargs) -> List[RawKLine]:
    df = pd.read_csv(path, **kwargs)
    return from_dataframe(df)


def to_dataframe(klines: List[RawKLine]) -> pd.DataFrame:
    return pd.DataFrame([{
        "date": k.dt, "open": k.open, "high": k.high,
        "low": k.low, "close": k.close, "volume": k.volume,
    } for k in klines])


def make_sample(n: int = 640, seed: int = 7) -> List[RawKLine]:
    """生成带有清晰缠论结构的合成日K线。

    结构: 下跌趋势 → 底部盘整(中枢) → 上涨趋势 → 顶部盘整(中枢) → 下跌。
    并在趋势末段刻意制造"背驰"(后段斜率减缓), 便于演示一类买卖点。
    返回长度约 n 的 RawKLine 列表 (确定性, 由 seed 控制)。
    """
    rng = np.random.default_rng(seed)
    # 分段漂移: (持续bar数, 每bar对数收益漂移)。以震荡开局避免单边起始的边界效应,
    # 趋势段与盘整段(中枢)交替, 趋势末段刻意趋缓以制造背驰。
    regimes = [
        (60, 0.000),    # 起始震荡
        (80, 0.011),    # 上涨
        (50, 0.000),    # 高位盘整 (中枢)
        (70, 0.010),    # 再上涨
        (50, 0.003),    # 上涨趋缓 -> 背驰
        (90, -0.012),   # 下跌
        (50, 0.000),    # 低位盘整 (中枢)
        (80, -0.010),   # 再下跌
        (40, -0.003),   # 下跌趋缓 -> 背驰
        (70, 0.011),    # 反弹
    ]
    closes = [100.0]
    for bars, drift in regimes:
        for _ in range(bars):
            shock = rng.normal(0, 0.024)
            closes.append(closes[-1] * float(np.exp(drift + shock)))
    closes = np.asarray(closes[1:])
    if len(closes) > n:
        closes = closes[:n]

    dates = pd.bdate_range("2023-01-02", periods=len(closes))
    out: List[RawKLine] = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        hi = max(o, c) * (1 + abs(rng.normal(0, 0.004)))
        lo = min(o, c) * (1 - abs(rng.normal(0, 0.004)))
        vol = float(rng.integers(8_000, 60_000))
        out.append(RawKLine(idx=i, dt=dates[i], open=float(o), high=float(hi),
                            low=float(lo), close=float(c), volume=vol))
        prev = c
    return out
