#!/usr/bin/env python3
"""Audit one dynamic Futu run and print its exact remaining capture queue.

This helper does not call Futu, capture data, or publish anything. It is intended
as a durable checkpoint after each exact MCP result has been captured.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

from capture_latest_futu_result import (
    load_expected_security_name,
    normalize_security_name,
    validate_bars,
    validate_returned_identity,
)


def load_universe(path):
    with open(path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"code", "name"}.issubset(reader.fieldnames):
            raise ValueError("Universe CSV must contain code and name columns")
        rows = list(reader)
    codes = []
    for row in rows:
        code = (row.get("code") or "").strip()
        name = (row.get("name") or "").strip()
        if not code or not name:
            raise ValueError("Universe contains an empty code or name")
        codes.append(code)
    if not codes:
        raise ValueError("Universe is empty")
    if len(codes) != len(set(codes)):
        raise ValueError("Universe contains duplicate codes")
    return rows, codes


def audit(universe_path, raw_dir, started_epoch):
    rows, codes = load_universe(universe_path)
    expected_names = {row["code"].strip(): normalize_security_name(row["name"]) for row in rows}
    raw_dir = Path(raw_dir)
    manifest_path = raw_dir / ".capture_manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"Capture manifest not found: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read capture manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Capture manifest must be a JSON object")
    extras = sorted(set(manifest) - set(codes))
    if extras:
        raise ValueError(f"Manifest contains codes outside this universe: {extras}")

    used_sources = set()
    for code, source_value in manifest.items():
        if not source_value:
            raise ValueError(f"Manifest source is empty for {code}")
        source = Path(source_value)
        if not source.is_file():
            raise ValueError(f"Manifest source file is missing for {code}: {source}")
        if source.stat().st_mtime < started_epoch:
            raise ValueError(f"Manifest source is stale for {code}: {source}")
        resolved = str(source.resolve())
        if resolved in used_sources:
            raise ValueError(f"Manifest reuses one source file for multiple symbols: {source}")
        used_sources.add(resolved)
        bar_path = raw_dir / f"{code}.json"
        if not bar_path.is_file():
            raise ValueError(f"Captured bar JSON is missing for {code}: {bar_path}")
        try:
            source_payload = json.loads(source.read_text(encoding="utf-8"))
            bar_payload = json.loads(bar_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid JSON for captured symbol {code}: {exc}") from exc
        if source_payload != bar_payload:
            raise ValueError(f"Captured JSON does not match manifest source for {code}")
        if source_payload.get("ret_code", 0) not in (0, "0", None):
            raise ValueError(f"Non-success Futu result in manifest for {code}")
        bars = source_payload.get("data", {}).get("kline_list", [])
        validate_bars(bars, code)
        validate_returned_identity(source_payload, code, expected_names[code])

    pending = [code for code in codes if code not in manifest]
    return {
        "status": "COMPLETE" if not pending else "INCOMPLETE",
        "universe_count": len(codes),
        "captured_count": len(manifest),
        "pending_count": len(pending),
        "pending_symbols": pending,
        "universe_symbols": codes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--raw-dir", required=True, help="Run bars directory containing the manifest")
    parser.add_argument("--started-epoch", required=True, type=float)
    parser.add_argument("--log-path", help="Append a concise checkpoint record to this private run log")
    parser.add_argument("--show-next", type=int, default=10, help="Number of next pending codes to display")
    args = parser.parse_args()
    if args.show_next < 1:
        parser.error("--show-next must be at least 1")
    try:
        result = audit(args.universe, args.raw_dir, args.started_epoch)
    except (OSError, ValueError, csv.Error, TypeError) as exc:
        message = f"CAPTURE_CHECKPOINT status=ERROR error={exc}"
        print(message, file=sys.stderr)
        if args.log_path:
            with open(args.log_path, "a", encoding="utf-8") as stream:
                stream.write(message.replace("\n", " ") + "\n")
        return 2

    next_codes = result["pending_symbols"][:args.show_next]
    record = (
        f"CAPTURE_CHECKPOINT status={result['status']} "
        f"universe={result['universe_count']} captured={result['captured_count']} "
        f"pending={result['pending_count']} next={','.join(next_codes) or '-'}"
    )
    print(json.dumps({**result, "next_symbols": next_codes}, ensure_ascii=False, indent=2))
    if args.log_path:
        with open(args.log_path, "a", encoding="utf-8") as stream:
            stream.write(record + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
