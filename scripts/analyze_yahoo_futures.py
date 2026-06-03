# -*- coding: utf-8 -*-
"""
Discover US futures on Yahoo Finance, fetch daily bars, and run ChanAnalyzer.

The Yahoo futures screener returns both continuous/head symbols such as ES=F
and dated contracts such as ESM26.CME.  This script analyzes every symbol whose
chart endpoint returns enough daily bars, then writes a CSV and a short report.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, Iterable, List
from urllib.parse import quote

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "futures_analysis")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
SCREENER_URL = "https://query1.finance.yahoo.com/v1/finance/screener"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_THREAD_LOCAL = threading.local()


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    session.get("https://fc.yahoo.com", timeout=30)
    session.get("https://finance.yahoo.com/research-hub/screener/futures/", timeout=30)
    crumb = session.get(
        "https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=30
    ).text.strip()
    session.params = {"crumb": crumb}
    return session


def chart_session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        _THREAD_LOCAL.session = session
    return session


def discover_futures(session: requests.Session, size: int = 250) -> List[Dict]:
    query = {
        "operator": "and",
        "operands": [{"operator": "eq", "operands": ["region", "us"]}],
    }
    offset = 0
    rows: List[Dict] = []
    total = None
    while total is None or offset < total:
        payload = {
            "size": size,
            "offset": offset,
            "sortField": "percentchange",
            "sortType": "DESC",
            "quoteType": "FUTURE",
            "query": query,
            "userId": "",
            "userIdType": "guid",
        }
        response = session.post(
            SCREENER_URL,
            params={"lang": "en-US", "region": "US", **session.params},
            json=payload,
            timeout=45,
        )
        response.raise_for_status()
        result = response.json()["finance"]["result"][0]
        total = int(result["total"])
        page = result.get("quotes", [])
        rows.extend(page)
        if not page:
            break
        offset += len(page)
    unique: Dict[str, Dict] = {}
    for row in rows:
        symbol = row.get("symbol")
        if symbol:
            unique[symbol] = row
    return sorted(unique.values(), key=lambda r: r["symbol"])


def fetch_chart(session: requests.Session, symbol: str, range_: str,
                timeout: float) -> pd.DataFrame:
    url = CHART_URL.format(symbol=quote(symbol, safe=""))
    response = session.get(
        url,
        params={"range": range_, "interval": "1d"},
        timeout=(5, timeout),
    )
    response.raise_for_status()
    data = response.json()
    chart = data.get("chart", {})
    if chart.get("error"):
        raise ValueError(chart["error"])
    result = chart.get("result") or []
    if not result:
        return pd.DataFrame()
    item = result[0]
    ts = item.get("timestamp") or []
    quote_data = (item.get("indicators", {}).get("quote") or [{}])[0]
    rows = []
    for i, t in enumerate(ts):
        try:
            o = quote_data["open"][i]
            h = quote_data["high"][i]
            l = quote_data["low"][i]
            c = quote_data["close"][i]
        except (KeyError, IndexError):
            continue
        if None in (o, h, l, c):
            continue
        rows.append({
            "date": datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": (quote_data.get("volume") or [0] * len(ts))[i] or 0,
        })
    return pd.DataFrame(rows)


def analyze_symbol(row: Dict, df: pd.DataFrame, zhongshu_mode: str) -> Dict:
    from chanlun.analyzer import ChanAnalyzer
    from chanlun.models import BSPType, TrendType

    ana = ChanAnalyzer(df, zhongshu_mode=zhongshu_mode).run()
    bsp_counts = Counter(b.bsp_type.value for b in ana.bsps)
    return {
        "symbol": row["symbol"],
        "short_name": row.get("shortName", ""),
        "exchange": row.get("exchange", ""),
        "full_exchange_name": row.get("fullExchangeName", ""),
        "contract_kind": "continuous" if row["symbol"].endswith("=F") else "dated",
        "bars": len(ana.raws),
        "first_date": str(ana.raws[0].dt)[:10] if ana.raws else "",
        "last_date": str(ana.raws[-1].dt)[:10] if ana.raws else "",
        "merged": len(ana.merged),
        "fractals": len(ana.fractals),
        "bis": len(ana.bis),
        "segments": len(ana.segments),
        "completed_segments": sum(1 for s in ana.segments if s.completed),
        "bi_zhongshus": len(ana.bi_zhongshus),
        "seg_zhongshus": len(ana.seg_zhongshus),
        "trend": ana.trend.name if isinstance(ana.trend, TrendType) else str(ana.trend),
        "buy_sell_points": len(ana.bsps),
        "buy1": bsp_counts[BSPType.BUY1.value],
        "buy2": bsp_counts[BSPType.BUY2.value],
        "buy3": bsp_counts[BSPType.BUY3.value],
        "sell1": bsp_counts[BSPType.SELL1.value],
        "sell2": bsp_counts[BSPType.SELL2.value],
        "sell3": bsp_counts[BSPType.SELL3.value],
        "applicable": bool(len(ana.bis) >= 3 and len(ana.bi_zhongshus) >= 1),
    }


def write_report(path: str, rows: List[Dict], discovered: int, skipped: Counter,
                 min_bars: int, range_: str, zhongshu_mode: str) -> None:
    analyzed = len(rows)
    applicable = [r for r in rows if r["applicable"]]
    continuous = [r for r in rows if r["contract_kind"] == "continuous"]
    dated = [r for r in rows if r["contract_kind"] == "dated"]
    by_exchange = Counter(r["exchange"] for r in rows)
    by_trend = Counter(r["trend"] for r in rows)
    by_kind = Counter(r["contract_kind"] for r in rows)
    top_bsps = sorted(rows, key=lambda r: r["buy_sell_points"], reverse=True)[:20]

    lines = [
        "# Yahoo US Futures Chan Analysis",
        "",
        f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Yahoo screener symbols discovered: {discovered}",
        f"- Chart range: `{range_}` daily bars; minimum bars required: {min_bars}",
        f"- Zhongshu mode: `{zhongshu_mode}`",
        f"- Analyzed symbols: {analyzed}",
        f"- Applicable by structural minimum (>=3 bi and >=1 bi zhongshu): {len(applicable)}",
        f"- Continuous analyzed: {len(continuous)}; dated analyzed: {len(dated)}",
        "",
        "## Skips",
        "",
    ]
    for key, value in sorted(skipped.items()):
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Breakdown", ""])
    lines.append("- By kind: " + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())))
    lines.append("- By trend: " + ", ".join(f"{k}={v}" for k, v in sorted(by_trend.items())))
    lines.append("- By exchange: " + ", ".join(f"{k}={v}" for k, v in sorted(by_exchange.items())))

    lines.extend(["", "## Top Symbols By Buy/Sell Points", ""])
    lines.append("| Symbol | Name | Kind | Bars | Bi | Zhongshu | Trend | BSP |")
    lines.append("|---|---|---:|---:|---:|---:|---|---:|")
    for r in top_bsps:
        name = str(r["short_name"]).replace("|", "/")[:48]
        lines.append(
            f"| {r['symbol']} | {name} | {r['contract_kind']} | {r['bars']} | "
            f"{r['bis']} | {r['bi_zhongshus']} | {r['trend']} | {r['buy_sell_points']} |"
        )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "Chan analysis is structurally applicable when a futures time series forms enough "
        "merged K-lines, alternating bi, and at least one zhongshu. Continuous futures "
        "are usually the cleaner universe because dated contracts often have short or "
        "thin histories. Dated contracts that pass the minimum-bar filter can still be "
        "analyzed, but their conclusions are more expiration-specific.",
        "",
    ])
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def is_standard_continuous(row: Dict) -> bool:
    symbol = str(row.get("symbol", ""))
    if not symbol.endswith("=F"):
        return False
    name = str(row.get("shortName", "")).lower()
    excluded_terms = [
        "tas", "btic", "spot", "ratio", "spread", "look-alik",
        "calendar", "tba", "transaction price",
    ]
    return not any(term in name for term in excluded_terms)


def iter_symbols(rows: Iterable[Dict], include_dated: bool,
                 only_standard_continuous: bool) -> List[Dict]:
    selected = [
        row for row in rows
        if include_dated or str(row.get("symbol", "")).endswith("=F")
    ]
    if only_standard_continuous:
        selected = [row for row in selected if is_standard_continuous(row)]
    return sorted(selected, key=lambda r: (not str(r["symbol"]).endswith("=F"), r["symbol"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--range", default="5y", dest="range_")
    parser.add_argument("--min-bars", type=int, default=120)
    parser.add_argument("--include-dated", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--chart-timeout", type=float, default=12.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--only-standard-continuous", action="store_true")
    parser.add_argument("--zhongshu-mode", default="extension",
                        choices=["extension", "same_level"])
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    session = make_session()
    discovered = discover_futures(session)
    symbols = iter_symbols(
        discovered, args.include_dated, args.only_standard_continuous)
    if args.limit:
        symbols = symbols[:args.limit]

    out_csv = os.path.join(OUT_DIR, "yahoo_us_futures_chan.csv")
    report_md = os.path.join(OUT_DIR, "yahoo_us_futures_chan_report.md")
    rows: List[Dict] = []
    skipped: Counter = Counter()

    def process(row: Dict):
        symbol = row["symbol"]
        try:
            df = fetch_chart(chart_session(), symbol, args.range_, args.chart_timeout)
            if len(df) < args.min_bars:
                return "skip", "too_few_bars", None
            return "row", None, analyze_symbol(row, df, args.zhongshu_mode)
        except Exception as exc:  # noqa: BLE001
            return "skip", type(exc).__name__, None

    if args.workers <= 1:
        for idx, row in enumerate(symbols, 1):
            kind, reason, result = process(row)
            if kind == "row":
                rows.append(result)
            else:
                skipped[reason] += 1
            if idx % 10 == 0:
                print(
                    f"processed {idx}/{len(symbols)}; analyzed={len(rows)}; "
                    f"skipped={sum(skipped.values())}",
                    flush=True,
                )
            time.sleep(args.sleep)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(process, row) for row in symbols]
            for idx, future in enumerate(as_completed(futures), 1):
                kind, reason, result = future.result()
                if kind == "row":
                    rows.append(result)
                else:
                    skipped[reason] += 1
                if idx % 25 == 0:
                    print(
                        f"processed {idx}/{len(symbols)}; analyzed={len(rows)}; "
                        f"skipped={sum(skipped.values())}",
                        flush=True,
                    )
                if args.sleep:
                    time.sleep(args.sleep)

    rows.sort(key=lambda r: (r["contract_kind"], r["symbol"]))

    fieldnames = [
        "symbol", "short_name", "exchange", "full_exchange_name", "contract_kind",
        "bars", "first_date", "last_date", "merged", "fractals", "bis",
        "segments", "completed_segments", "bi_zhongshus", "seg_zhongshus",
        "trend", "buy_sell_points", "buy1", "buy2", "buy3", "sell1", "sell2",
        "sell3", "applicable",
    ]
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    write_report(report_md, rows, len(discovered), skipped, args.min_bars,
                 args.range_, args.zhongshu_mode)
    print(json.dumps({
        "discovered": len(discovered),
        "selected": len(symbols),
        "analyzed": len(rows),
        "skipped": dict(skipped),
        "csv": out_csv,
        "report": report_md,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
