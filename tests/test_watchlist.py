# -*- coding: utf-8 -*-
"""自选清单解析 (scripts/scan_latest_futures_signals.load_watchlist) 单元测试。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scan_latest_futures_signals import load_watchlist  # noqa: E402


def test_load_watchlist_parsing(tmp_path):
    csv_path = tmp_path / "wl.csv"
    csv_path.write_text(
        "symbol,name,note,enabled\n"
        "ES=F,E-mini S&P 500,index,true\n"
        "CL=F,WTI Crude,,\n"          # enabled 留空 -> 视为启用
        "GC=F,Gold,,false\n"         # 停用 -> 跳过
        "# 注释行,,,\n"               # symbol 以 # 开头 -> 跳过
        "ES=F,dup,,true\n"           # 重复 symbol -> 跳过
        "AAPL,Apple Inc.,stock,TRUE\n",  # 大小写不敏感
        encoding="utf-8",
    )
    wl = load_watchlist(str(csv_path))
    assert [r["symbol"] for r in wl] == ["ES=F", "CL=F", "AAPL"]
    assert wl[0]["shortName"] == "E-mini S&P 500"
    assert wl[1]["shortName"] == "WTI Crude"      # 有 name 用 name
    assert wl[2]["shortName"] == "Apple Inc."


def test_load_watchlist_minimal_columns(tmp_path):
    # 只有 symbol 一列也能工作, shortName 回退为 symbol
    csv_path = tmp_path / "wl2.csv"
    csv_path.write_text("symbol\nNQ=F\n000001.SS\n", encoding="utf-8")
    wl = load_watchlist(str(csv_path))
    assert [r["symbol"] for r in wl] == ["NQ=F", "000001.SS"]
    assert wl[0]["shortName"] == "NQ=F"


def test_repo_watchlist_is_valid():
    # 仓库内置的 data/watchlist.csv 应可解析且至少含一个启用品种
    wl = load_watchlist(str(ROOT / "data" / "watchlist.csv"))
    assert len(wl) >= 1
    assert all(r["symbol"] for r in wl)
