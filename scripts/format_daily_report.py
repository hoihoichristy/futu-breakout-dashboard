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
    "SMA200 unavailable": "SMA200未驗證",
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


def core_status(row):
    """Return the explicit three-state core result, with legacy CSV compatibility."""
    status = (row.get("core_status") or "").strip().lower()
    if status in ("pass", "fail", "unverified"):
        return status
    return "pass" if (row.get("pass_core") or "").strip().lower() in ("true", "1", "yes") else "fail"


def core_label(row):
    return {"pass": "通過", "fail": "未通過", "unverified": "未完整驗證"}[core_status(row)]


def has_unverified_sma200(row):
    conditions = (row.get("unverified_conditions") or "").upper()
    failures = (row.get("failures") or "").upper()
    return (
        "SMA200" in conditions
        or "SMA200 UNAVAILABLE" in failures
        or (core_status(row) == "unverified" and number(row, "above_sma200_pct") is None)
    )


def sma200_text(row):
    value = number(row, "above_sma200_pct")
    if value is not None:
        return pct(value, True)
    return "未驗證" if has_unverified_sma200(row) else "—"


def render(rows, as_of, expected, dashboard_url=""):
    if len(rows) != expected:
        raise ValueError(f"Expected {expected} metrics rows, received {len(rows)}")
    codes = [r.get("code", "").strip() for r in rows]
    if not all(codes) or len(set(codes)) != expected:
        raise ValueError("Missing or duplicate stock codes in metrics CSV")

    # Preserve core-pass priority, then rank by the existing three-EMA mean distance.
    rows.sort(key=lambda r: (
        core_status(r) != "pass",
        number(r, "ema_mean_distance_pct") if number(r, "ema_mean_distance_pct") is not None else 1e9,
        abs(number(r, "trigger_gap_pct") or 0),
    ))
    passed = sum(core_status(r) == "pass" for r in rows)
    unverified = sum(core_status(r) == "unverified" for r in rows)
    breakouts = sum(r.get("breakout_close", "").strip().lower() in ("true", "1", "yes") for r in rows)
    lines = [
        f"## Futu 美股突破觀察 — {as_of}",
        "",
        f"覆蓋 **{len(rows)} 檔使用者設定的普通股／ADR**；核心條件完整通過 **{passed} 檔**（不含 **{unverified} 檔**核心未完整驗證）；收盤高於此前 20 日高點 **{breakouts} 檔**。",
        "",
        "| 股票全名（代號） | K線根數 | 收盤 | 63日報酬 | ADR20 | 50日均成交額 | 高於SMA200 | 最窄整固 | 距前20日高點 | 收盤突破 | EMA三線均距 | 核心條件 | 驗證註記 | 未通過條件 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---:|:---:|---|---|",
    ]
    for r in rows:
        close = number(r, "close")
        turnover = number(r, "turnover50")
        base_pct = number(r, "best_base_pct")
        base_days = number(r, "best_base_days")
        emad = number(r, "ema_mean_distance_pct")
        bars = number(r, "bars")
        fail_raw = [x.strip() for x in (r.get("failures") or "").split(";") if x.strip()]
        failures = "、".join(FAILURE_ZH.get(x, x) for x in fail_raw) or "—"
        breakout = r.get("breakout_close", "").strip().lower() in ("true", "1", "yes")
        base = "—" if base_pct is None or base_days is None else f"{base_days:.0f}日/{base_pct:.2f}%"
        close_text = "—" if close is None else f"${close:.2f}"
        bars_text = "—" if bars is None else f"{bars:.0f}根"
        note = (r.get("validation_note") or "").strip() or ("SMA200未驗證" if has_unverified_sma200(r) else "—")
        lines.append(
            f"| {r.get('name', '')} ({r['code']}) | {bars_text} | {close_text} | "
            f"{pct(number(r, 'return_63_pct'), True)} | {pct(number(r, 'adr20_pct'))} | "
            f"{'—' if turnover is None else f'${turnover / 1e6:.1f}m'} | "
            f"{sma200_text(r)} | {base} | {pct(number(r, 'trigger_gap_pct'), True)} | "
            f"{'是' if breakout else '否'} | {pct(emad)} | {core_label(r)} | {note} | {failures} |"
        )
    lines.extend([
        "",
        f"**說明：** ADR20 為平均日內振幅，不是 Wilder ATR；負的「距前20日高點」代表收盤高於該高點。收盤越過前高僅是價位事件，未確認成交量或後續延續。固定清單中所有股票日 K 至少 64 根但未滿 200 根均可保留；此類 SMA200 一律標示「未驗證」，不以較短歷史平均替代，也不計入完整核心通過。此清單更新既有 {len(rows)} 檔，不是全美股市值篩選。",
        "",
    ])
    if dashboard_url:
        lines.append(f"[開啟互動式 EMA／突破／回踩 dashboard]({dashboard_url})")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metrics", required=True)
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    ap.add_argument("--expected-count", type=int, default=53)
    ap.add_argument("--output", help="Write Markdown to this path; otherwise print to stdout")
    ap.add_argument("--dashboard-url", default="", help="Optional public dashboard URL")
    args = ap.parse_args()
    with open(args.metrics, newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    report = render(rows, args.as_of, args.expected_count, args.dashboard_url)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        print(f"Report: {path}")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
