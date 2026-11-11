#!/usr/bin/env python3
"""Capture and validate one exact Futu quote_history_kline result.

For dynamic runs, pass the exact MCP result path and the current run's screened
universe. The returned security name must match that universe row before either
the symbol JSON or capture manifest is written.
"""
import argparse
import csv
import json
import math
from pathlib import Path
from validation_policy import minimum_bars


def normalize_security_name(value):
    """Normalize only case and whitespace; do not fuzzy-match security names."""
    return " ".join(str(value or "").split()).casefold()


def load_expected_security_name(universe_csv, symbol):
    with open(universe_csv, newline="", encoding="utf-8-sig") as stream:
        rows = csv.DictReader(stream)
        if not rows.fieldnames or "code" not in rows.fieldnames or "name" not in rows.fieldnames:
            raise ValueError("Universe CSV must contain code and name columns")
        matches = [row for row in rows if row.get("code", "").strip() == symbol]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one universe row for {symbol}; found {len(matches)}"
        )
    expected = normalize_security_name(matches[0].get("name"))
    if not expected:
        raise ValueError(f"Universe has no security name for {symbol}")
    return expected


def validate_returned_identity(payload, symbol, expected_name):
    bars = payload.get("data", {}).get("kline_list", [])
    names = {
        normalize_security_name(bar.get("name"))
        for bar in bars
        if normalize_security_name(bar.get("name"))
    }
    if names != {expected_name}:
        raise ValueError(
            f"Security name mismatch for {symbol}: expected={expected_name!r}, "
            f"returned={sorted(names)!r}"
        )


def validate_bars(bars, symbol):
    if not bars:
        raise ValueError(f"Empty K-line series for {symbol}")
    dates = [str(bar.get("date", "")) for bar in bars]
    if any(not date for date in dates):
        raise ValueError(f"Missing bar date for {symbol}")
    if len(dates) != len(set(dates)):
        raise ValueError(f"Duplicate bar dates for {symbol}")
    for index, bar in enumerate(bars):
        vals = {}
        for field in ("open", "high", "low", "close"):
            try:
                vals[field] = float(bar[field])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid {field} in bar {index} for {symbol}") from exc
            if not math.isfinite(vals[field]) or vals[field] <= 0:
                raise ValueError(f"Invalid {field} in bar {index} for {symbol}")
        if vals["high"] < max(vals["open"], vals["close"], vals["low"]):
            raise ValueError(f"Inconsistent OHLC high in bar {index} for {symbol}")
        if vals["low"] > min(vals["open"], vals["close"], vals["high"]):
            raise ValueError(f"Inconsistent OHLC low in bar {index} for {symbol}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", required=True, help="Futu symbol, e.g. US.MSFT")
    ap.add_argument("--started-epoch", required=True, type=float,
                    help="Unix timestamp recorded before this run's first Futu call")
    ap.add_argument("--source-dir", default="/home/ubuntu/.mcp/tool-results")
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--source-file", help="Exact result path returned by this MCP call")
    ap.add_argument("--min-bars", type=int, default=200)
    ap.add_argument("--dynamic-screen", action="store_true",
                    help="Use only for symbols in this run's Futu-screened universe")
    ap.add_argument("--screened-universe", help="Current run's screened universe CSV")
    args = ap.parse_args()

    expected_name = None
    if args.dynamic_screen:
        if not args.screened_universe:
            raise SystemExit("--dynamic-screen requires --screened-universe")
        if not args.source_file:
            raise SystemExit("Dynamic capture requires exact --source-file from this Futu call")
        try:
            expected_name = load_expected_security_name(args.screened_universe, args.symbol)
        except (OSError, csv.Error, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        required_bars = max(1, args.min_bars)
    else:
        required_bars = minimum_bars(args.symbol, args.min_bars)

    source_path = Path(args.source_file) if args.source_file else None
    if source_path is None:
        candidates = list(Path(args.source_dir).glob("*quote_history_kline*.json"))
    else:
        candidates = [source_path]

    raw_dir = Path(args.raw_dir)
    manifest_path = raw_dir / ".capture_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read capture manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise SystemExit("Capture manifest must be a JSON object")
    if args.symbol in manifest:
        raise SystemExit(f"Symbol already captured in this run: {args.symbol}")
    captured_sources = {str(Path(value).resolve()) for value in manifest.values() if value}

    candidates = [
        path for path in candidates
        if path.is_file()
        and path.stat().st_mtime >= args.started_epoch
        and str(path.resolve()) not in captured_sources
    ]
    candidates.sort(key=lambda path: (path.stat().st_mtime_ns, path.name), reverse=True)

    selected = None
    payload = None
    problems = []
    for path in candidates:
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            ret_code = current.get("ret_code", 0)
            if ret_code not in (0, "0", None):
                problems.append(f"{path.name}: ret_code={ret_code}")
                continue
            bars = current.get("data", {}).get("kline_list", [])
            if len({str(bar.get('date', '')) for bar in bars}) < required_bars:
                problems.append(f"{path.name}: only {len(bars)} bars; minimum={required_bars}")
                continue
            validate_bars(bars, args.symbol)
            if expected_name is not None:
                validate_returned_identity(current, args.symbol, expected_name)
            selected, payload = path, current
            break
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            problems.append(f"{path.name}: {exc}")
            # An exact dynamic source must never fall through to another file.
            if args.dynamic_screen:
                break

    if selected is None:
        detail = "; ".join(problems[-3:])
        raise SystemExit(f"No fresh valid Futu K-line result for {args.symbol}. {detail}")

    bars = sorted(payload["data"]["kline_list"], key=lambda bar: str(bar["date"]))
    latest = bars[-1]
    raw_dir.mkdir(parents=True, exist_ok=True)
    out = raw_dir / f"{args.symbol}.json"

    # Validate fully before writing; use atomic replacements so an interrupted
    # write cannot leave a partial symbol JSON or manifest.
    temp_out = out.with_name(out.name + ".tmp")
    temp_manifest = manifest_path.with_name(manifest_path.name + ".tmp")
    manifest[args.symbol] = str(selected.resolve())
    try:
        temp_out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        temp_out.replace(out)
        temp_manifest.replace(manifest_path)
    finally:
        temp_out.unlink(missing_ok=True)
        temp_manifest.unlink(missing_ok=True)

    print(f"captured {args.symbol}: {len(bars)} bars; latest={latest.get('date')}; source={selected.name}")
    if len(bars) < 200:
        print(f"short-history exception {args.symbol}: minimum={required_bars}; SMA200 unavailable, not a verified core pass")


if __name__ == "__main__":
    main()
