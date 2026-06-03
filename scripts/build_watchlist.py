# -*- coding: utf-8 -*-
"""生成/合并 data/watchlist.csv：主流期货 + 中国指数 + 美股七姐妹。

合并语义(默认): 读取已有清单, **保留你手工编辑过的所有行**(含 name/note/enabled),
仅追加其中尚不存在的 symbol —— 绝不覆盖你的改动。

期货来源由 --futures 控制:
  * mainstream (默认): 一份精选主流流动性合约白名单(各大类活跃品种, 约 60 个);
  * all              : screener 全部"标准连续"合约(约 180+, 含较多冷门品种);
  * none             : 不加期货(只补指数/个股)。
名称在可联网时用 Yahoo screener 实时补全, 否则用内置名称。

用法:
    python scripts/build_watchlist.py                  # 主流期货 + 指数 + 七姐妹
    python scripts/build_watchlist.py --futures all    # 改用全部标准连续期货
    python scripts/build_watchlist.py --reset          # 先清空再生成(不保留旧行)
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
for path in (ROOT, SCRIPTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from analyze_yahoo_futures import (  # noqa: E402
    discover_futures, is_standard_continuous, make_session,
)

FIELDS = ["symbol", "name", "note", "enabled"]

# 精选主流期货 (各大类活跃合约, symbol -> 内置名称回退)
MAINSTREAM_FUTURES = [
    # 股指
    ("ES=F", "E-mini S&P 500"), ("MES=F", "Micro E-mini S&P 500"),
    ("NQ=F", "E-mini Nasdaq 100"), ("MNQ=F", "Micro E-mini Nasdaq 100"),
    ("YM=F", "E-mini Dow"), ("MYM=F", "Micro E-mini Dow"),
    ("RTY=F", "E-mini Russell 2000"), ("M2K=F", "Micro E-mini Russell 2000"),
    ("EMD=F", "E-mini S&P MidCap 400"), ("NKD=F", "Nikkei 225 (USD)"),
    # 利率/国债
    ("ZT=F", "2-Year T-Note"), ("ZF=F", "5-Year T-Note"),
    ("ZN=F", "10-Year T-Note"), ("TN=F", "Ultra 10-Year T-Note"),
    ("ZB=F", "U.S. Treasury Bond"), ("UB=F", "Ultra U.S. Treasury Bond"),
    ("ZQ=F", "30-Day Fed Funds"),
    # 外汇
    ("DX=F", "U.S. Dollar Index"), ("6E=F", "Euro FX"),
    ("6J=F", "Japanese Yen"), ("6B=F", "British Pound"),
    ("6A=F", "Australian Dollar"), ("6C=F", "Canadian Dollar"),
    ("6S=F", "Swiss Franc"), ("6N=F", "New Zealand Dollar"),
    ("6M=F", "Mexican Peso"), ("CNH=F", "USD/Offshore RMB"),
    # 金属
    ("GC=F", "Gold"), ("MGC=F", "Micro Gold"), ("SI=F", "Silver"),
    ("SIL=F", "Micro Silver"), ("HG=F", "Copper"), ("MHG=F", "Micro Copper"),
    ("PL=F", "Platinum"), ("PA=F", "Palladium"), ("ALI=F", "Aluminum"),
    # 能源
    ("CL=F", "WTI Crude Oil"), ("MCL=F", "Micro WTI Crude Oil"),
    ("BZ=F", "Brent Crude Oil"), ("NG=F", "Natural Gas"),
    ("RB=F", "RBOB Gasoline"), ("HO=F", "Heating Oil"),
    # 谷物/油籽
    ("ZC=F", "Corn"), ("ZS=F", "Soybeans"), ("ZW=F", "Chicago Wheat"),
    ("KE=F", "KC HRW Wheat"), ("ZL=F", "Soybean Oil"),
    ("ZM=F", "Soybean Meal"), ("ZO=F", "Oats"), ("ZR=F", "Rough Rice"),
    # 软商品
    ("KC=F", "Coffee"), ("CC=F", "Cocoa"), ("SB=F", "Sugar No.11"),
    ("CT=F", "Cotton"), ("OJ=F", "Orange Juice"), ("LBR=F", "Lumber"),
    # 畜产品
    ("LE=F", "Live Cattle"), ("GF=F", "Feeder Cattle"), ("HE=F", "Lean Hogs"),
    # 加密
    ("BTC=F", "Bitcoin"), ("MBT=F", "Micro Bitcoin"),
    ("ETH=F", "Ether"), ("MET=F", "Micro Ether"),
]

# 中国 / 香港 指数 (Yahoo 代码)
CN_INDICES = [
    ("000001.SS", "上证综指"), ("399001.SZ", "深证成指"),
    ("399006.SZ", "创业板指"), ("000300.SS", "沪深300"),
    ("000905.SS", "中证500"), ("000016.SS", "上证50"),
    ("000688.SS", "科创50"), ("000852.SS", "中证1000"),
    ("^HSI", "恒生指数"), ("^HSTECH", "恒生科技指数"),
    ("^HSCE", "恒生中国企业指数"),
]

# 美股「七姐妹」(Magnificent Seven)
MAG7 = [
    ("AAPL", "Apple 苹果"), ("MSFT", "Microsoft 微软"),
    ("GOOGL", "Alphabet 谷歌"), ("AMZN", "Amazon 亚马逊"),
    ("NVDA", "NVIDIA 英伟达"), ("META", "Meta"),
    ("TSLA", "Tesla 特斯拉"),
]

# A股/港股指数 ETF 代理: Yahoo 对这些指数本身(.SS/.SZ)覆盖不稳, 但对应 ETF 可稳定取数,
# 用 ETF 跟踪相应指数 (实测均可取到~1200根日线)。
CN_ETF_PROXIES = [
    ("510050.SS", "上证50ETF(华夏·跟踪上证50)"),
    ("510500.SS", "中证500ETF(南方·跟踪中证500)"),
    ("512100.SS", "中证1000ETF(南方·跟踪中证1000)"),
    ("159915.SZ", "创业板ETF(易方达·跟踪创业板指)"),
    ("588000.SS", "科创50ETF(华夏·跟踪科创50)"),
    ("513130.SS", "恒生科技ETF(华泰柏瑞·跟踪恒生科技)"),
]

_EXTRA_JUNK = ["trading se", "look-alik", "transaction pr"]

# 经实测 Yahoo chart 端点不能稳定返回日线(常仅 1 根或 4xx)的代码: **直接排除, 不写入清单**。
# 多为 Yahoo 数据覆盖问题, 与真实流动性无关(如 Micro WTI); 若日后 Yahoo 恢复可手动加回。
# 全尺寸合约(CL/HG/BTC/ETH 等)与可用指数(沪深300/上证综指/恒生等)已覆盖相应敞口。
UNRELIABLE = {
    "EMD=F", "MHG=F", "MCL=F", "MBT=F", "MET=F", "DX=F",          # 期货
    "399006.SZ", "000905.SS", "000016.SS", "000688.SS",          # A股指数
    "000852.SS", "^HSTECH",                                       # A股/港股指数
}


def clean(text: str) -> str:
    return " ".join(str(text or "").split())


def read_existing(path: Path):
    rows, seen = [], set()
    if not path.exists():
        return rows, seen
    with open(path, encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            rec = {(k or "").strip().lower(): (v or "").strip()
                   for k, v in raw.items()}
            sym = rec.get("symbol", "")
            if not sym:
                continue
            rows.append({"symbol": sym, "name": rec.get("name", ""),
                         "note": rec.get("note", ""),
                         "enabled": rec.get("enabled", "true") or "true"})
            seen.add(sym)
    return rows, seen


def _screener_names() -> dict:
    """可联网时返回 {symbol: shortName}; 失败则空字典 (用内置名称回退)。"""
    try:
        session = make_session()
        return {r.get("symbol"): clean(r.get("shortName") or "")
                for r in discover_futures(session)}
    except Exception as exc:  # noqa: BLE001
        print("(screener 不可用, 用内置名称) %r" % exc)
        return {}


def _is_clean_continuous(row) -> bool:
    if not is_standard_continuous(row):
        return False
    sym = str(row.get("symbol", ""))
    name = clean(row.get("shortName") or "")
    if not name or name.upper() == sym.upper():
        return False
    low = name.lower()
    return not any(term in low for term in _EXTRA_JUNK)


def futures_rows(mode: str):
    if mode == "none":
        return []
    if mode == "all":
        names = _screener_names()  # 同时拿到全集
        session = make_session()
        rows = [r for r in discover_futures(session) if _is_clean_continuous(r)]
        rows.sort(key=lambda r: r["symbol"])
        return [(r["symbol"], clean(r.get("shortName") or r["symbol"])) for r in rows]
    # mainstream
    names = _screener_names()
    return [(sym, names.get(sym) or fallback) for sym, fallback in MAINSTREAM_FUTURES]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "watchlist.csv"))
    ap.add_argument("--futures", choices=["mainstream", "all", "none"],
                    default="mainstream")
    ap.add_argument("--reset", action="store_true",
                    help="先清空再生成(不保留旧行)")
    args = ap.parse_args()

    out = Path(args.out)
    rows, seen = ([], set()) if args.reset else read_existing(out)
    before = len(rows)

    candidates = [(s, n, "期货(主流)" if args.futures == "mainstream" else "期货(标准连续)")
                  for s, n in futures_rows(args.futures)]
    candidates += [(s, n, "中国指数") for s, n in CN_INDICES]
    candidates += [(s, n, "中国指数(ETF代理)") for s, n in CN_ETF_PROXIES]
    candidates += [(s, n, "美股七姐妹") for s, n in MAG7]

    added = 0
    for sym, name, note in candidates:
        if sym in seen or sym in UNRELIABLE:   # Yahoo 取不到数据的直接排除
            continue
        seen.add(sym)
        rows.append({"symbol": sym, "name": name, "note": note, "enabled": "true"})
        added += 1

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    enabled = sum(1 for r in rows if str(r["enabled"]).lower()
                  not in {"false", "0", "no", "n", "off"})
    print("写入 %s" % out)
    print("  原有 %d 行, 新增 %d 行, 现共 %d 行 (启用 %d)" %
          (before, added, len(rows), enabled))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
