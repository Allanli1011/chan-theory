# -*- coding: utf-8 -*-
"""
拉取真实日线行情(Yahoo Finance chart API), 保存为 data/<symbol>.csv。

Yahoo 接口返回 JSON, 字段含 timestamp 与 open/high/low/close/volume。
用系统 curl 抓取(避免 python-requests 被部分 WAF 拦截)。
用法: python scripts/fetch_data.py AAPL 000001.SS ...
"""
import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

CURL = shutil.which("curl") or shutil.which("curl.exe") or r"C:\Windows\System32\curl.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
URL = ("https://query1.finance.yahoo.com/v8/finance/chart/"
       "{sym}?range={rng}&interval=1d")


def fetch(symbol: str, rng: str = "5y") -> str:
    url = URL.format(sym=symbol, rng=rng)
    p = subprocess.run([CURL, "-s", "-L", "--max-time", "40",
                        "-A", "Mozilla/5.0", url], capture_output=True, timeout=60)
    text = p.stdout.decode("utf-8", errors="replace")
    data = json.loads(text)
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, symbol.replace("^", "") + ".csv")
    rows = 0
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for i, t in enumerate(ts):
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            if None in (o, h, l, c):
                continue
            d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
            v = q.get("volume", [0] * len(ts))[i] or 0
            w.writerow([d, "%.4f" % o, "%.4f" % h, "%.4f" % l, "%.4f" % c, int(v)])
            rows += 1
    print("saved %s (%d rows) -> %s" % (symbol, rows, path))
    return path


if __name__ == "__main__":
    syms = sys.argv[1:] or ["AAPL", "000001.SS"]
    for s in syms:
        try:
            fetch(s)
        except Exception as e:  # noqa: BLE001
            print("!! failed %s: %r" % (s, e))
