# -*- coding: utf-8 -*-
"""
缠论分析端到端示例。

用法:
    python examples/demo.py                 # 用内置合成数据
    python examples/demo.py data/AAPL.csv   # 用CSV(列: date,open,high,low,close[,volume])

输出: 控制台分析摘要 + 同目录下 PNG 标注图。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 让 print 在重定向到非UTF-8管道时也不崩
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from chanlun.analyzer import ChanAnalyzer          # noqa: E402
from chanlun.data import load_csv, make_sample      # noqa: E402
from chanlun.plot import plot_analysis              # noqa: E402


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_csv = os.path.join(root, "data", "000001.SS.csv")
    if len(sys.argv) > 1:
        path = sys.argv[1]
        raws = load_csv(path)
        name = os.path.splitext(os.path.basename(path))[0]
    elif os.path.exists(default_csv):     # 优先用随仓库附带的真实行情(上证指数)
        raws = load_csv(default_csv)
        name = "000001.SS"
    else:
        raws = make_sample(seed=7)
        name = "sample"

    ana = ChanAnalyzer(raws).run()
    print(ana.summary())

    # 只画最后 ~240 根K线, 标注更清晰
    start = max(0, len(ana.raws) - 240)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chart_%s.png" % name)
    plot_analysis(ana, start=start, save_path=out,
                  title="%s 缠论分析 (笔/线段/中枢/买卖点)" % name)
    print("\n图已保存: %s" % out)


if __name__ == "__main__":
    main()
