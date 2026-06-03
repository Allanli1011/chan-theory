# -*- coding: utf-8 -*-
"""
多级别递归分析示例 (课17: 级别递归体系)。

同一份日线数据重采样到周线/月线, 分别做缠论分析, 体现"不同显微镜倍数"。
用法: python examples/multi_level.py data/000001.SS.csv
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import pandas as pd  # noqa: E402

from chanlun.analyzer import analyze_multi_level  # noqa: E402


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "data/000001.SS.csv"
    df = pd.read_csv(path)
    levels = {"日线": None, "周线": "W", "月线": "ME"}
    res = analyze_multi_level(df, levels)
    print("级别       K线   笔   线段  中枢  走势类型  买卖点")
    print("-" * 52)
    for name, a in res.items():
        print("%-8s %5d %4d %5d %5d  %-6s  %4d" % (
            name, len(a.raws), len(a.bis), len(a.segments),
            len(a.bi_zhongshus), str(a.trend), len(a.bsps)))


if __name__ == "__main__":
    main()
