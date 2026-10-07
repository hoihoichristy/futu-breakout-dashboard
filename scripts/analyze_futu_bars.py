#!/usr/bin/env python3
"""Analyze saved Futu quote_history_kline JSON files and optionally plot breakout watches."""
import argparse
import csv
import glob
import json
import os
import statistics
import sys
from datetime import datetime


def ema(values, period):
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def load_bars(paths):
    by_name = {}
    for pattern in paths:
        matches = glob.glob(pattern)
        for path in matches or [pattern]:
            if not os.path.isfile(path):
                continue
            try:
                payload = json.load(open(path, encoding="utf-8"))
                bars = payload.get("data", {}).get("kline_list", [])
                if not bars:
                    continue
                bars = sorted(bars, key=lambda bar: bar["date"])
                name = bars[-1].get("name") or bars[-1].get("code") or os.path.basename(path)
                current = by_name.get(name)
                # Prefer the longest history; break ties using newest last bar.
                if current is None or (len(bars), bars[-1]["date"]) > (len(current), current[-1]["date"]):
                    by_name[name] = bars
            except (OSError, ValueError, KeyError, TypeError) as exc:
                print(f"Warning: skipped {path}: {exc}", file=sys.stderr)
    return by_name


def analyze(name, bars):
    closes = [float(bar["close"]) for bar in bars]
    latest = bars[-1]
    close = closes[-1]
    date = str(latest["date"])
    result = {"name": name, "date": date, "close": close, "bars": len(bars)}
    result["return_63_pct"] = (close / closes[-64] - 1) * 100 if len(closes) >= 64 else None
    result["adr20_pct"] = statistics.mean(
        (float(bar["high"]) - float(bar["low"])) / float(bar["close"]) * 100 for bar in bars[-20:]
    ) if len(bars) >= 20 else None
    turnovers = [float(bar.get("turnover", 0) or 0) for bar in bars[-50:]]
    result["turnover50"] = statistics.mean(turnovers) if len(turnovers) == 50 else None
    result["above_sma200_pct"] = (
        (close / statistics.mean(closes[-200:]) - 1) * 100 if len(closes) >= 200 else None
    )
    bases = []
    for count in range(5, min(39, len(bars)) + 1):
        window = bars[-count:]
        low = min(float(bar["low"]) for bar in window)
        high = max(float(bar["high"]) for bar in window)
        bases.append(((high - low) / low * 100, count))
    result["best_base_pct"], result["best_base_days"] = min(bases) if bases else (None, None)
    if len(bars) >= 21:
        prior20 = bars[-21:-1]
        result["prior20_low"] = min(float(bar["low"]) for bar in prior20)
        result["prior20_high"] = max(float(bar["high"]) for bar in prior20)
        result["above_prior20_low"] = close >= result["prior20_low"]
        result["trigger_gap_pct"] = (result["prior20_high"] - close) / result["prior20_high"] * 100
        result["breakout_close"] = close > result["prior20_high"]
    else:
        result.update(prior20_low=None, prior20_high=None, above_prior20_low=None,
                      trigger_gap_pct=None, breakout_close=None)
    for period in (10, 20, 50):
        result[f"ema{period}"] = ema(closes, period) if len(closes) >= period else None
        result[f"ema{period}_distance_pct"] = (
            abs(close / result[f"ema{period}"] - 1) * 100 if result[f"ema{period}"] else None
        )
    result["pass_core"] = all([
        result["return_63_pct"] is not None and result["return_63_pct"] >= 20,
        close > 5,
        result["turnover50"] is not None and result["turnover50"] > 5_000_000,
        result["adr20_pct"] is not None and result["adr20_pct"] > 3.5,
        result["above_sma200_pct"] is not None and result["above_sma200_pct"] <= 60,
        result["best_base_pct"] is not None and result["best_base_pct"] < 8,
        result["above_prior20_low"] is True,
    ])
    failures = []
    tests = [
        (result["return_63_pct"] is not None and result["return_63_pct"] >= 20, "3m return"),
        (close > 5, "price"),
        (result["turnover50"] is not None and result["turnover50"] > 5_000_000, "50d turnover"),
        (result["adr20_pct"] is not None and result["adr20_pct"] > 3.5, "ADR20"),
        (result["above_sma200_pct"] is not None and result["above_sma200_pct"] <= 60, "200d cap"),
        (result["best_base_pct"] is not None and result["best_base_pct"] < 8, "base width"),
        (result["above_prior20_low"] is True, "above prior 20d low"),
    ]
    result["failures"] = [label for passed, label in tests if not passed]
    return result


def chart(rows, by_name, output):
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import Rectangle

    chart_rows = sorted(
        [row for row in rows if row["prior20_high"] is not None],
        key=lambda row: (not row["breakout_close"], abs(row["trigger_gap_pct"])),
    )[:4]
    if not chart_rows:
        print("No stocks have enough bars for a 20-session breakout chart.", file=sys.stderr)
        return
    fig, axes = plt.subplots(len(chart_rows), 1, figsize=(12, 3.15 * len(chart_rows)), squeeze=False)
    axes = [axis for [axis] in axes]
    fig.suptitle("Futu Stock Screen — Breakout Watch (daily candles)", fontsize=15, fontweight="bold")
    for ax, row in zip(axes, chart_rows):
        bars = by_name[row["name"]][-60:]
        dates = [datetime.strptime(str(bar["date"]), "%Y%m%d") for bar in bars]
        for dt, bar in zip(dates, bars):
            open_, close = float(bar["open"]), float(bar["close"])
            high, low = float(bar["high"]), float(bar["low"])
            color = "#16865b" if close >= open_ else "#d04a44"
            ax.vlines(dt, low, high, color=color, linewidth=1)
            ax.add_patch(Rectangle((mdates.date2num(dt) - .28, min(open_, close)), .56,
                                   max(abs(close - open_), close * .0005),
                                   facecolor=color, edgecolor=color, linewidth=.5))
        last = bars[-1]
        close = float(last["close"])
        trigger = row["prior20_high"]
        ema20 = row["ema20"]
        status = "Close above trigger" if row["breakout_close"] else f"{row['trigger_gap_pct']:.1f}% below trigger"
        ax.axhline(trigger, color="#e09b24", linestyle="--", linewidth=1.5,
                   label=f"Prior 20-session high / trigger: ${trigger:.2f}")
        if ema20:
            ax.axhline(ema20, color="#547da5", linestyle=":", linewidth=1.4,
                       label=f"EMA20: ${ema20:.2f}")
        ax.scatter(dates[-1], close, color="#111111", s=26, zorder=4)
        ax.set_title(f"{row['name']} — {row['date']} close ${close:.2f} | {status}", loc="left", fontsize=10, fontweight="bold")
        ax.set_ylabel("Price"); ax.grid(axis="y", alpha=.22); ax.legend(loc="upper left", fontsize=8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d")); ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.margins(x=.02)
    fig.text(.01, .004, "Source: Futu daily OHLC. A close above the prior high is price-only; volume/follow-through confirmation is not assessed.", fontsize=8)
    fig.tight_layout(rect=[0, .02, 1, .95])
    fig.savefig(output, dpi=180, bbox_inches="tight")
    print(f"Chart: {os.path.abspath(output)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", help="Futu quote_history_kline JSON result file(s) or glob patterns")
    parser.add_argument("--chart", help="Optional output PNG path for a breakout-watch chart")
    parser.add_argument("--csv", help="Optional output CSV path for calculated metrics")
    args = parser.parse_args()
    candles = load_bars(args.files)
    if not candles:
        parser.error("No valid Futu data.kline_list arrays found in input files")
    rows = [analyze(name, bars) for name, bars in candles.items()]
    rows.sort(key=lambda row: (not row["pass_core"], row["trigger_gap_pct"] is None,
                               abs(row["trigger_gap_pct"] or 999)))
    print("Name | As of | Close | 63-session return | ADR20 | 50d turnover | vs SMA200 | tightest base | breakout gap | Core pass | Misses")
    for row in rows:
        def fmt(value, spec):
            return "n/a" if value is None else format(value, spec)
        base = "n/a" if row["best_base_pct"] is None else f"{row['best_base_days']}d/{row['best_base_pct']:.1f}%"
        turnover = "n/a" if row["turnover50"] is None else f"${row['turnover50']/1e6:.1f}m"
        gap = "n/a" if row["trigger_gap_pct"] is None else f"{row['trigger_gap_pct']:+.1f}%"
        print(f"{row['name']} | {row['date']} | ${row['close']:.2f} | {fmt(row['return_63_pct'],'.1f')}% | {fmt(row['adr20_pct'],'.2f')}% | {turnover} | {fmt(row['above_sma200_pct'],'+.1f')}% | {base} | {gap} | {'YES' if row['pass_core'] else 'NO'} | {', '.join(row['failures']) or '—'}")
    if args.csv:
        keys = list(rows[0].keys())
        with open(args.csv, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=keys); writer.writeheader(); writer.writerows(rows)
        print(f"CSV: {os.path.abspath(args.csv)}")
    if args.chart:
        chart(rows, candles, args.chart)


if __name__ == "__main__":
    main()
