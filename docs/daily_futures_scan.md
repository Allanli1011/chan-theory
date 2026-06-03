# Daily Futures Chan Scan

The scheduled workflow is defined in:

```text
.github/workflows/daily-futures-chan-scan.yml
```

It runs at `23:30 UTC` from Monday through Friday, which is safely after the
common 17:00 US futures session break in both US daylight and standard time.

## Outputs

Each run writes to a folder named by the scan date:

```text
data/futures_latest_signals/YYYY-MM-DD/latest_chan_signals.csv
data/futures_latest_signals/YYYY-MM-DD/index.md
data/futures_latest_signals/YYYY-MM-DD/charts/*.png
```

The CSV contains one row per newly recognized `1B`, `2B`, `3B`, `1S`, `2S`, or
`3S` signal. The chart directory contains one Chan-annotated chart per product
that produced at least one new signal in the scan.

## New Signal Rule

The scanner analyzes each futures symbol twice:

1. with the latest daily bar included
2. with the latest daily bar removed

A buy/sell point is considered new when it exists only in the first analysis.
This handles Chan confirmation lag: a signal may be dated a few bars before the
latest bar, but it may only become structurally confirmable after the newest bar
closes.

By default, the script ignores newly appearing signals whose signal point is
more than 20 daily bars behind the latest bar. This avoids noisy historical
reclassification. Use `--max-signal-age-bars 0` to disable that filter.

## Manual Run

```bash
python scripts/scan_latest_futures_signals.py --range 5y --min-bars 120 --workers 6
```

Useful options:

```bash
--include-dated              Include dated contracts, not only =F symbols.
--only-standard-continuous   Exclude TAS/BTIC/spread-like continuous symbols.
--symbols ES=F,CL=F          Scan an explicit comma-separated symbol list.
--limit N                    Scan only the first N selected symbols.
--plot-bars N                Number of latest daily bars shown in each chart.
--run-date YYYY-MM-DD        Override the date folder name for backfills.
```
