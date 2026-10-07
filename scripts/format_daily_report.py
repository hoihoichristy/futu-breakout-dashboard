#!/usr/bin/env python3
"""Render a Traditional Chinese daily report table from validated Futu metrics CSV."""
import argparse
import csv
from pathlib import Path

FAILURE_ZH = {
    "3m return": "3月報酬<20%",
    "price": "股價≤$5",
    "50d turnover": "50日成交額≤$5m",
    "ADR20": "ADR20≤3.5%",
    "200d cap": "高於SMA200>60%",
    "base width": "整固幅度≥8%",
    "above prior 20d low": "收盤低於前20日低點",
}


def number(row, key):
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return None


def pct(value, signed=False):
    if value is None:
        return "—"
    return f"{value:+.2f}%" if signed else f"{value:.2f}%"


def render(rows, as_of, expected):
    if len(rows) != expected:
        raise ValueError(f"Expected {expected} metrics rows, received {len(rows)}")
    codes = [r.get("code", "").strip() for r in rows]
    if not all(codes) or len(set(codes)) != expected:
        raise ValueError("Missing or duplicate stock codes in metrics CSV")
    rows.sort(key=lambda r: (
        r.get("pass_core", "").strip().lower() not in ("true", "1", "yes"),
        number(r, "ema_mean_distance_pct") if number(r, "ema_mean_distance_pct") is not None else 1e9,
        abs(number(r, "trigger_gap_pct") or 0),
    ))
    passed = sum(r.get("pass_core", "").strip().lower() in ("true", "1", "yes") for r in rows)
    breakouts = sum(r.get("breakout_close", "").strip().lower() in ("true", "1", "yes") for r in rows)
    lines = [
        f"## Futu 美股突破觀察 — {as_of}",
        "",
        f"覆蓋 **{len(rows)} 檔固定普通股／ADR**；核心條件同時通過 **{passed} 檔**；收盤高於此前 20 日高點 **{breakouts} 檔**。",
        "",
        "| 股票全名（代號） | 收盤 | 63日報酬 | ADR20 | 50日均成交額 | 高於SMA200 | 最窄整固 | 距前20日高點 | 收盤突破 | EMA三線均距 | 核心條件 | 未通過條件 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|:---:|---:|:---:|---|",
    ]
    for r in rows:
        close = number(r, "close")
        turnover = number(r, "turnover50")
        base_pct = number(r, "best_base_pct")
        base_days = number(r, "best_base_days")
        emad = number(r, "ema_mean_distance_pct")
        fail_raw = [x.strip() for x in (r.get("failures") or "").split(";") if x.strip()]
        failures = "、".join(FAILURE_ZH.get(x, x) for x in fail_raw) or "—"
        passed_row = r.get("pass_core", "").strip().lower() in ("true", "1", "yes")
        breakout = r.get("breakout_close", "").strip().lower() in ("true", "1", "yes")
        base = "—" if base_pct is None else f"{base_days:.0f}日/{base_pct:.2f}%"
        close_text = "—" if close is None else f"${close:.2f}"
        lines.append(
            f"| {r.get('name','')} ({r['code']}) | "
            f"{close_text} | "
            f"{pct(number(r,'return_63_pct'),True)} | {pct(number(r,'adr20_pct'))} | "
            f"{'—' if turnover is None else f'${turnover/1e6:.1f}m'} | "
            f"{pct(number(r,'above_sma200_pct'),True)} | {base} | "
            f"{pct(number(r,'trigger_gap_pct'),True)} | {'是' if breakout else '否'} | "
            f"{pct(emad)} | {'通過' if passed_row else '未通過'} | {failures} |"
        )
    lines.extend([
        "",
        "**說明：** ADR20 為平均日內振幅，不是 Wilder ATR；負的「距前20日高點」代表收盤高於該高點。收盤越過前高僅是價位事件，未確認成交量或後續延續。此清單每日更新既有 53 檔，不是全美股市值篩選。",
        "",
        "[開啟互動式 EMA／突破／回踩 dashboard](https://hoihoichristy.github.io/futu-breakout-dashboard/)",
    ])
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metrics", required=True)
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    ap.add_argument("--expected-count", type=int, default=53)
    ap.add_argument("--output", help="Write Markdown to this path; otherwise print to stdout")
    args = ap.parse_args()
    with open(args.metrics, newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    report = render(rows, args.as_of, args.expected_count)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        print(f"Report: {path}")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
