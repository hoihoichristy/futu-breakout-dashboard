#!/usr/bin/env python3
"""Recalculate the Futu breakout dashboard from symbol-named daily-bar JSON files.

This script intentionally refreshes the existing reviewed 53-symbol universe only;
it does not claim to rescreen all U.S. stocks or add new candidates.
"""
import argparse
import csv
import json
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_futu_bars as analyzer  # noqa: E402
import build_interactive_dashboard as dashboard  # noqa: E402


def normalize_date(value):
    text = str(value).strip().replace("-", "")
    if len(text) < 8 or not text[:8].isdigit():
        raise ValueError(f"Invalid Futu bar date: {value!r}")
    return text[:8]


def load_universe(path, expected):
    with open(path, newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    required = {"code", "name", "Futu_security_type", "US_listing_class"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"Universe CSV must contain: {', '.join(sorted(required))}")
    if len(rows) != expected:
        raise ValueError(f"Expected {expected} reviewed symbols; universe has {len(rows)}")
    codes = [r["code"].strip() for r in rows]
    if len(set(codes)) != len(codes):
        raise ValueError("Duplicate symbol codes in universe CSV")
    return [{k: (r.get(k) or "").strip() for k in required} for r in rows]


def load_symbol_bars(raw_dir, symbol, min_bars):
    path = Path(raw_dir) / f"{symbol}.json"
    if not path.is_file():
        raise ValueError(f"Missing fresh Futu result for {symbol}: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    ret_code = payload.get("ret_code", 0)
    if ret_code not in (0, "0", None):
        raise ValueError(f"Futu returned ret_code={ret_code} for {symbol}: {payload.get('ret_msg', '')}")
    bars = payload.get("data", {}).get("kline_list", [])
    if len(bars) < min_bars:
        raise ValueError(f"{symbol}: got {len(bars)} bars; need at least {min_bars}")
    # Stable date ordering and one bar per session.
    by_date = {}
    for bar in bars:
        date = normalize_date(bar["date"])
        by_date[date] = bar
    bars = [by_date[d] for d in sorted(by_date)]
    for bar in bars:
        for field in ("open", "high", "low", "close"):
            float(bar[field])
    if len(bars) < min_bars:
        raise ValueError(f"{symbol}: only {len(bars)} unique dated bars")
    return bars, normalize_date(bars[-1]["date"])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--universe", required=True)
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--output", required=True, help="Write to a temporary path, not the live repo file")
    ap.add_argument("--expected-count", type=int, default=53)
    ap.add_argument("--min-bars", type=int, default=200)
    ap.add_argument("--metrics-output", help="Optional CSV path for the validated metrics table")
    args = ap.parse_args()

    universe = load_universe(args.universe, args.expected_count)
    rows, bars_by_code, latest_dates = [], {}, {}
    for meta in universe:
        bars, latest_date = load_symbol_bars(args.raw_dir, meta["code"], args.min_bars)
        latest_dates[meta["code"]] = latest_date
        row = analyzer.analyze(meta["name"], bars)
        row["code"] = meta["code"]
        row["Futu_security_type"] = meta["Futu_security_type"]
        row["US_listing_class"] = meta["US_listing_class"]
        rows.append(row)
        bars_by_code[meta["code"]] = [{
            "date": normalize_date(b["date"]), "open": float(b["open"]),
            "high": float(b["high"]), "low": float(b["low"]), "close": float(b["close"]),
        } for b in bars]

    if len(set(latest_dates.values())) != 1:
        counts = Counter(latest_dates.values())
        raise ValueError("Latest bar dates differ across symbols; refusing partial/stale publish: " +
                         ", ".join(f"{d} ({n} symbols)" for d, n in sorted(counts.items())))

    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8-sig", suffix=".csv") as stream:
        fields = list(rows[0].keys())
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        stream.flush()
        checked_rows, excluded = dashboard.load_metrics(stream.name, common_adr_only=True)

    if excluded or len(checked_rows) != args.expected_count:
        raise ValueError(f"Security-class validation changed the universe: kept={len(checked_rows)}, excluded={len(excluded)}")

    if args.metrics_output:
        metrics_path = Path(args.metrics_output)
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        with metrics_path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(checked_rows[0].keys()))
            writer.writeheader()
            for checked in checked_rows:
                row = dict(checked)
                row["failures"] = "; ".join(failure for failure in
                                             next(item["failures"] for item in rows if item["code"] == row["code"]))
                row["rules"] = "; ".join("pass" if value else "fail" for value in row.get("rules", []))
                writer.writerow(row)

    as_of = datetime.strptime(next(iter(set(latest_dates.values()))), "%Y%m%d").strftime("%Y-%m-%d")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    html = dashboard.build_html(checked_rows, bars_by_code,
                                "Futu 美股普通股與 ADR｜互動式突破／回踩儀表板", as_of)
    out.write_text(html, encoding="utf-8")
    if "const D=" not in html or "const B=" not in html or len(checked_rows) != args.expected_count:
        out.unlink(missing_ok=True)
        raise ValueError("Generated dashboard failed structural validation")
    print(json.dumps({
        "status": "built", "as_of": as_of, "symbols": len(checked_rows),
        "core_pass": sum(bool(r["pass_core"]) for r in checked_rows),
        "price_breakouts": sum(bool(r["breakout_close"]) for r in checked_rows),
        "bars_per_symbol_min": min(len(v) for v in bars_by_code.values()),
        "output": str(out),
        "metrics_output": args.metrics_output,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
