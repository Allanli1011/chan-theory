# -*- coding: utf-8 -*-
"""Daily Yahoo futures scan for newly recognized Chan buy/sell points.

The scanner compares the current daily-bar analysis with the same analysis on
the data set minus its latest bar. A signal is considered "new" when it appears
only after the latest daily bar is included. This catches Chan signals whose
actual signal point is a few bars back but only becomes confirmable today.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
for path in (ROOT, SCRIPTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from analyze_yahoo_futures import (  # noqa: E402
    DEFAULT_CHART_CACHE_DIR,
    chart_session,
    discover_futures,
    fetch_chart_cached,
    iter_symbols,
    make_session,
)
from chanlun.analyzer import ChanAnalyzer  # noqa: E402
from chanlun.models import BSPType, BuySellPoint  # noqa: E402
from chanlun.plot import plot_analysis  # noqa: E402

DEFAULT_OUTPUT_ROOT = ROOT / "data" / "futures_latest_signals"

SIGNAL_CODES = {
    BSPType.BUY1: "1B",
    BSPType.BUY2: "2B",
    BSPType.BUY3: "3B",
    BSPType.SELL1: "1S",
    BSPType.SELL2: "2S",
    BSPType.SELL3: "3S",
}


@dataclass
class SymbolScan:
    row: Dict
    df: pd.DataFrame
    analyzer: ChanAnalyzer
    new_signals: List[BuySellPoint]


def signal_code(bsp_type: BSPType) -> str:
    return SIGNAL_CODES[bsp_type]


def signal_side(bsp_type: BSPType) -> str:
    return "BUY" if bsp_type.name.startswith("BUY") else "SELL"


def signal_class(bsp_type: BSPType) -> int:
    return int(bsp_type.name[-1])


def signal_key(signal: BuySellPoint) -> Tuple[str, int, str, float]:
    return (
        signal.bsp_type.name,
        int(signal.raw_idx),
        str(signal.dt)[:10],
        round(float(signal.price), 8),
    )


def find_new_signals(current: ChanAnalyzer, previous: ChanAnalyzer,
                     max_signal_age_bars: int) -> List[BuySellPoint]:
    previous_keys = {signal_key(signal) for signal in previous.bsps}
    newest_raw_idx = len(current.raws) - 1
    signals: List[BuySellPoint] = []
    for signal in current.bsps:
        if signal_key(signal) in previous_keys:
            continue
        age = newest_raw_idx - int(signal.raw_idx)
        if max_signal_age_bars > 0 and age > max_signal_age_bars:
            continue
        signals.append(signal)
    return signals


def safe_symbol(symbol: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in symbol)


def chart_title(row: Dict) -> str:
    symbol = row["symbol"]
    name = str(row.get("shortName") or row.get("longName") or "").strip()
    name = " ".join(name.split())
    if not name or name == symbol:
        return f"{symbol}\nChan latest signals"
    if len(name) > 72:
        name = name[:69].rstrip() + "..."
    return f"{symbol} - {name}\nChan latest signals"


def relpath(path: Path) -> str:
    try:
        return os.path.relpath(path, ROOT).replace(os.sep, "/")
    except ValueError:
        # Windows: 输出目录与仓库不在同一盘符时 relpath 会抛错, 回退绝对路径
        return str(path).replace(os.sep, "/")


def default_run_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_watchlist(path: str) -> List[Dict]:
    """从 CSV 自选清单读取要扫描的品种。

    列约定 (表头不区分大小写):
      * symbol   : 必填, Yahoo 代码 (期货 ES=F / 个股 AAPL / 指数 000001.SS / 加密 BTC-USD 皆可);
      * name     : 选填, 显示名 (用于图表标题与 short_name);
      * note     : 选填, 备注, 程序忽略;
      * enabled  : 选填, false/0/no/off 表示停用该行, 缺省视为启用。
    symbol 以 '#' 开头的行视为注释跳过; 重复 symbol 只保留首次。
    """
    rows: List[Dict] = []
    seen = set()
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            record = {(k or "").strip().lower(): (v or "").strip()
                      for k, v in raw.items()}
            symbol = (record.get("symbol") or record.get("ticker")
                      or record.get("code") or "")
            if not symbol or symbol.startswith("#"):
                continue
            enabled = (record.get("enabled") or record.get("active") or "true").lower()
            if enabled in {"false", "0", "no", "n", "off"}:
                continue
            if symbol in seen:
                continue
            seen.add(symbol)
            name = (record.get("name") or record.get("short_name")
                    or record.get("shortname") or symbol)
            rows.append({"symbol": symbol, "shortName": name})
    return rows


def analyze_symbol_for_new_signals(row: Dict, range_: str, min_bars: int,
                                   chart_timeout: float,
                                   zhongshu_mode: str,
                                   max_signal_age_bars: int,
                                   cache_dir: str | None,
                                   cache_refresh_range: str,
                                   force_refresh: bool):
    symbol = row["symbol"]
    try:
        df = fetch_chart_cached(
            chart_session(), symbol, range_, chart_timeout, cache_dir,
            cache_refresh_range, force_refresh,
        )
        if len(df) < min_bars:
            return "skip", "too_few_bars", None
        if len(df) < 2:
            return "skip", "not_enough_bars_for_delta", None

        analyzer = ChanAnalyzer(df, zhongshu_mode=zhongshu_mode).run()
        previous = ChanAnalyzer(df.iloc[:-1].copy(),
                                zhongshu_mode=zhongshu_mode).run()
        new_signals = find_new_signals(
            analyzer, previous, max_signal_age_bars)
        return "row", None, SymbolScan(row, df, analyzer, new_signals)
    except Exception as exc:  # noqa: BLE001
        return "skip", type(exc).__name__, None


def scan_symbols(symbols: Sequence[Dict], args) -> Tuple[List[SymbolScan], Counter]:
    scans: List[SymbolScan] = []
    skipped: Counter = Counter()

    def process(row: Dict):
        return analyze_symbol_for_new_signals(
            row=row,
            range_=args.range_,
            min_bars=args.min_bars,
            chart_timeout=args.chart_timeout,
            zhongshu_mode=args.zhongshu_mode,
            max_signal_age_bars=args.max_signal_age_bars,
            cache_dir=None if args.no_cache else args.cache_dir,
            cache_refresh_range=args.cache_refresh_range,
            force_refresh=args.force_refresh,
        )

    if args.workers <= 1:
        for idx, row in enumerate(symbols, 1):
            kind, reason, result = process(row)
            if kind == "row":
                scans.append(result)
            else:
                skipped[reason] += 1
            if idx % 10 == 0:
                print_progress(idx, len(symbols), scans, skipped)
            if args.sleep:
                time.sleep(args.sleep)
        return scans, skipped

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(process, row) for row in symbols]
        for idx, future in enumerate(as_completed(futures), 1):
            kind, reason, result = future.result()
            if kind == "row":
                scans.append(result)
            else:
                skipped[reason] += 1
            if idx % 25 == 0:
                print_progress(idx, len(symbols), scans, skipped)
            if args.sleep:
                time.sleep(args.sleep)
    return scans, skipped


def print_progress(idx: int, total: int, scans: Iterable[SymbolScan],
                   skipped: Counter) -> None:
    scans_list = list(scans)
    signal_symbols = sum(1 for scan in scans_list if scan.new_signals)
    print(
        f"processed {idx}/{total}; analyzed={len(scans_list)}; "
        f"signal_symbols={signal_symbols}; skipped={sum(skipped.values())}",
        flush=True,
    )


def clean_chart_dir(chart_dir: Path) -> None:
    chart_dir.mkdir(parents=True, exist_ok=True)
    for path in chart_dir.glob("*.png"):
        path.unlink()


def write_signal_outputs(scans: Sequence[SymbolScan], out_dir: Path,
                         chart_dir: Path, plot_bars: int) -> List[Dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    clean_chart_dir(chart_dir)

    signal_scans = [scan for scan in scans if scan.new_signals]
    chart_paths: Dict[str, Path] = {}
    for scan in signal_scans:
        symbol = scan.row["symbol"]
        chart_path = chart_dir / f"chan_{safe_symbol(symbol)}.png"
        start = max(0, len(scan.analyzer.raws) - plot_bars)
        plot_analysis(scan.analyzer, start=start, save_path=str(chart_path),
                      title=chart_title(scan.row))
        chart_paths[symbol] = chart_path

    scan_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows: List[Dict] = []
    for scan in signal_scans:
        symbol = scan.row["symbol"]
        analyzer = scan.analyzer
        latest = analyzer.raws[-1]
        chart_path = chart_paths[symbol]
        for signal in scan.new_signals:
            age = len(analyzer.raws) - 1 - int(signal.raw_idx)
            rows.append({
                "scan_time_utc": scan_time,
                "recognized_date": str(latest.dt)[:10],
                "symbol": symbol,
                "short_name": scan.row.get("shortName", ""),
                "exchange": scan.row.get("exchange", ""),
                "full_exchange_name": scan.row.get("fullExchangeName", ""),
                "contract_kind": (
                    "continuous" if symbol.endswith("=F") else "other"
                ),
                "signal": signal_code(signal.bsp_type),
                "signal_type": signal.bsp_type.name,
                "side": signal_side(signal.bsp_type),
                "class": signal_class(signal.bsp_type),
                "signal_date": str(signal.dt)[:10],
                "signal_bar_age": age,
                "price": f"{float(signal.price):.8g}",
                "latest_close": f"{float(latest.close):.8g}",
                "trend": analyzer.trend.name,
                "bars": len(analyzer.raws),
                "bis": len(analyzer.bis),
                "bi_zhongshus": len(analyzer.bi_zhongshus),
                "reason": signal.reason,
                "beichi_ratio": (
                    "" if signal.beichi_ratio is None
                    else f"{float(signal.beichi_ratio):.6g}"
                ),
                "ref_zs_idx": (
                    "" if signal.ref_zs_idx is None else signal.ref_zs_idx
                ),
                "ref_zs_zd": (
                    "" if signal.ref_zs_zd is None
                    else f"{float(signal.ref_zs_zd):.8g}"
                ),
                "ref_zs_zg": (
                    "" if signal.ref_zs_zg is None
                    else f"{float(signal.ref_zs_zg):.8g}"
                ),
                "ref_zs_raw_start": (
                    "" if signal.ref_zs_raw_start is None
                    else signal.ref_zs_raw_start
                ),
                "ref_zs_raw_end": (
                    "" if signal.ref_zs_raw_end is None
                    else signal.ref_zs_raw_end
                ),
                "chart_path": relpath(chart_path),
            })

    rows.sort(key=lambda row: (
        row["recognized_date"], row["symbol"], row["class"], row["side"]
    ))
    return rows


def write_csv(path: Path, rows: Sequence[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "scan_time_utc", "recognized_date", "symbol", "short_name",
        "exchange", "full_exchange_name", "contract_kind", "signal",
        "signal_type", "side", "class", "signal_date", "signal_bar_age",
        "price", "latest_close", "trend", "bars", "bis", "bi_zhongshus",
        "reason", "beichi_ratio", "ref_zs_idx", "ref_zs_zd", "ref_zs_zg",
        "ref_zs_raw_start", "ref_zs_raw_end", "chart_path",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_index(path: Path, rows: Sequence[Dict], skipped: Counter,
                discovered: int, selected: int, run_date: str) -> None:
    lines = [
        "# Latest Yahoo Chan Signals",
        "",
        f"- Generated UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"- Date folder: {run_date}",
        f"- Candidate symbols: {discovered}",
        f"- Symbols scanned: {selected}",
        f"- New signal rows: {len(rows)}",
        f"- Products with new signals: {len({row['symbol'] for row in rows})}",
        "",
        "## Skips",
        "",
    ]
    if skipped:
        lines.extend(f"- {key}: {value}" for key, value in sorted(skipped.items()))
    else:
        lines.append("- None")

    lines.extend(["", "## Signals", ""])
    if not rows:
        lines.append("No newly recognized Chan buy/sell points in this scan.")
    else:
        lines.append("| Symbol | Name | Signal | Ref ZS | Signal Date | Age | Price | Trend | Chart |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---|---|")
        for row in rows:
            name = str(row["short_name"]).replace("|", "/")[:48]
            ref_zs = "" if row["ref_zs_idx"] == "" else f"ZS{row['ref_zs_idx']}"
            chart_link = os.path.relpath(
                ROOT / row["chart_path"], path.parent).replace(os.sep, "/")
            lines.append(
                f"| {row['symbol']} | {name} | {row['signal']} | "
                f"{ref_zs} | {row['signal_date']} | {row['signal_bar_age']} | "
                f"{row['price']} | {row['trend']} | "
                f"[chart]({chart_link}) |"
            )

    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--range", default="5y", dest="range_")
    parser.add_argument("--min-bars", type=int, default=120)
    parser.add_argument("--include-dated", action="store_true")
    parser.add_argument("--symbols", default="",
                        help="Comma-separated symbols to scan instead of screener selection")
    parser.add_argument("--watchlist", default="",
                        help="CSV watchlist path (cols: symbol[,name,note,enabled]); "
                             "when set, scans exactly those symbols and skips the screener")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--chart-timeout", type=float, default=12.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--cache-dir", default=DEFAULT_CHART_CACHE_DIR)
    parser.add_argument("--cache-refresh-range", default="10d")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--only-standard-continuous", action="store_true")
    parser.add_argument("--zhongshu-mode", default="same_level",
                        choices=["extension", "same_level"])
    parser.add_argument("--max-signal-age-bars", type=int, default=20,
                        help="0 disables the recent-age filter")
    parser.add_argument("--plot-bars", type=int, default=360)
    parser.add_argument("--run-date", default=default_run_date(),
                        help="Date folder name, default is current UTC date")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--output-dir", default="",
                        help="Override the dated output directory")
    parser.add_argument("--chart-dir", default="",
                        help="Override chart directory, default is OUTPUT_DIR/charts")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else Path(args.output_root).resolve() / args.run_date
    )
    chart_dir = (
        Path(args.chart_dir).resolve()
        if args.chart_dir
        else out_dir / "charts"
    )
    csv_path = out_dir / "latest_chan_signals.csv"
    index_path = out_dir / "index.md"

    if args.symbols:
        # 显式给定逗号分隔代码: 用期货 screener 补全元数据, 缺失则用代码本身
        session = make_session()
        discovered = discover_futures(session)
        requested = [symbol.strip() for symbol in args.symbols.split(",")
                     if symbol.strip()]
        by_symbol = {row["symbol"]: row for row in discovered}
        symbols = [
            by_symbol.get(symbol, {"symbol": symbol, "shortName": symbol})
            for symbol in requested
        ]
        discovered_count = len(discovered)
    elif args.watchlist:
        # 自选清单模式: 只扫清单内品种, 不访问期货 screener
        symbols = load_watchlist(args.watchlist)
        discovered_count = len(symbols)
    else:
        # 默认: 期货 screener 自动发现
        session = make_session()
        discovered = discover_futures(session)
        symbols = iter_symbols(
            discovered, args.include_dated, args.only_standard_continuous)
        discovered_count = len(discovered)
    if args.limit:
        symbols = symbols[:args.limit]

    scans, skipped = scan_symbols(symbols, args)
    rows = write_signal_outputs(scans, out_dir, chart_dir, args.plot_bars)
    write_csv(csv_path, rows)
    write_index(index_path, rows, skipped, discovered_count, len(symbols),
                args.run_date)

    print(json.dumps({
        "discovered": discovered_count,
        "selected": len(symbols),
        "analyzed": len(scans),
        "new_signal_rows": len(rows),
        "new_signal_symbols": len({row["symbol"] for row in rows}),
        "skipped": dict(skipped),
        "csv": str(csv_path),
        "index": str(index_path),
        "chart_dir": str(chart_dir),
        "cache_dir": "" if args.no_cache else str(Path(args.cache_dir).resolve()),
        "cache_refresh_range": args.cache_refresh_range,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
