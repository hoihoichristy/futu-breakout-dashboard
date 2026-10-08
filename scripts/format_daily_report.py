#!/usr/bin/env python3
"""Render a Traditional Chinese daily report table from validated Futu metrics CSV."""
import argparse
import csv
import json
import math
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

CORE_MISSING_LABELS = (
    ("return_63_pct", "63日報酬"), ("close", "收盤價"),
    ("turnover50", "50日均成交額"), ("adr20_pct", "ADR20"),
    ("above_sma200_pct", "SMA200"), ("best_base_pct", "整固幅度"),
)


def number(row, key):
    try:
        value = float(row[key])
        return value if math.isfinite(value) else None
    except (KeyError, TypeError, ValueError):
        return None


def pct(value, signed=False):
    if value is None:
        return "未驗證"
    return f"{value:+.2f}%" if signed else f"{value:.2f}%"


def boolean(row, key):
    value = row.get(key)
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "y"):
        return True
    if text in ("false", "0", "no", "n"):
        return False
    return None


def append_unique(items, values):
    for value in values:
        if value and value not in items:
            items.append(value)
    return items


def unverified_conditions(row):
    """Return display labels for every unavailable metric, without failure labels."""
    labels = [part.strip() for part in (row.get("unverified_conditions") or "").split(";") if part.strip()]
    for field, label in CORE_MISSING_LABELS:
        if number(row, field) is None:
            append_unique(labels, [label])
    if number(row, "best_base_days") is None:
        append_unique(labels, ["整固幅度"])
    if number(row, "prior20_low") is None or boolean(row, "above_prior20_low") is None:
        append_unique(labels, ["前20日低點"])
    if number(row, "prior20_high") is None or boolean(row, "breakout_close") is None:
        append_unique(labels, ["前20日高點／突破"])
    for period in (10, 20, 50):
        if number(row, f"ema{period}") is None or number(row, f"ema{period}_distance_pct") is None:
            append_unique(labels, [f"EMA{period}"])
    return labels


def eligible(row):
    value = boolean(row, "metric_eligible")
    return value is not False and (row.get("market_status") or "ACTIVE").upper() != "SUSPENDED"


def core_rules(row):
    """Seven core screening conditions as True, False, or None (unverified)."""
    base_pct, base_days = number(row, "best_base_pct"), number(row, "best_base_days")
    if not eligible(row):
        return (None,) * 7
    return (
        None if number(row, "return_63_pct") is None else number(row, "return_63_pct") >= 20,
        None if number(row, "close") is None else number(row, "close") > 5,
        None if number(row, "turnover50") is None else number(row, "turnover50") > 5_000_000,
        None if number(row, "adr20_pct") is None else number(row, "adr20_pct") > 3.5,
        None if number(row, "above_sma200_pct") is None else number(row, "above_sma200_pct") <= 60,
        None if base_pct is None or base_days is None else base_pct < 8,
        boolean(row, "above_prior20_low"),
    )


def confirmed_failures(row):
    keys = ("3m return", "price", "50d turnover", "ADR20", "200d cap", "base width", "above prior 20d low")
    return [FAILURE_ZH[key] for key, result in zip(keys, core_rules(row)) if result is False]


def core_status(row):
    """Return a core pass only after every core rule has a verified result."""
    rules = core_rules(row)
    if any(result is None for result in rules):
        return "unverified"
    return "pass" if all(rules) else "fail"


def core_label(row):
    return {"pass": "通過", "fail": "未通過", "unverified": "未驗證"}[core_status(row)]


def has_unverified_sma200(row):
    return number(row, "above_sma200_pct") is None or "SMA200" in " ".join(unverified_conditions(row)).upper()


def sma200_text(row):
    value = number(row, "above_sma200_pct")
    if value is not None:
        return pct(value, True)
    return "未驗證"


def validation_note(row):
    """Keep the producer's detail while ensuring every missing display label is named."""
    labels = unverified_conditions(row)
    summary = "未驗證：" + "；".join(labels) if labels else ""
    existing = (row.get("validation_note") or "").strip()
    if existing and (not eligible(row) or not summary or all(label in existing for label in labels)):
        return existing
    if existing and summary:
        return f"{existing}；{summary}"
    return existing or summary or "—"


def display_date(value):
    text = str(value or '').replace('-', '')
    return f'{text[:4]}-{text[4:6]}-{text[6:]}' if len(text) == 8 and text.isdigit() else '未驗證'


def render(rows, as_of, expected=None, dashboard_url="", screen_summary=None):
    if expected is not None and len(rows) != expected:
        raise ValueError(f"Expected {expected} metrics rows, received {len(rows)}")
    codes = [r.get("code", "").strip() for r in rows]
    if not all(codes) or len(set(codes)) != len(rows):
        raise ValueError("Missing or duplicate stock codes in metrics CSV")

    # Core passes are first; failures and unverified rows share the second tier.
    # Unknown EMA means always rank last within a tier.
    rows.sort(key=lambda r: (
        not (eligible(r) and core_status(r) == "pass"),
        not eligible(r),
        number(r, "ema_mean_distance_pct") if eligible(r) and number(r, "ema_mean_distance_pct") is not None else 1e9,
        r.get("name", ""),
        r.get("code", ""),
    ))
    passed = sum(eligible(r) and core_status(r) == "pass" for r in rows)
    unverified = sum(eligible(r) and core_status(r) == "unverified" for r in rows)
    breakouts = sum(eligible(r) and boolean(r, "breakout_close") is True for r in rows)
    normal = sum(eligible(r) for r in rows)
    suspended = len(rows) - normal
    common_dates = sorted({display_date(r.get("analysis_date", "")) for r in rows if eligible(r) and r.get("analysis_date")})
    screen_line = ""
    if screen_summary:
        raw_count = screen_summary.get("screener_total", "未驗證")
        excluded_count = screen_summary.get("excluded_count", "未驗證")
        screen_line = (f"Futu 本輪市場篩選器找到 **{raw_count} 檔初篩候選**；"
                       f"經股票／證券類別檢核與排除後，分析 **{len(rows)} 檔普通股／ADR**（另排除 {excluded_count} 檔 ETF、非股票類或明確非普通股標的）。")
    lines = [
        f"## Futu 美股突破觀察 — {as_of}",
        "",
        screen_line or f"本輪動態篩選並完成分析 **{len(rows)} 檔普通股／ADR**（非固定 53 檔清單）。",
        f"本輪已分析 **{len(rows)} 檔動態篩選出的普通股／ADR**（正常 **{normal}**、停牌 **{suspended}**）；正常交易核心條件完整通過 **{passed} 檔**（另有 **{unverified} 檔**核心未驗證）；收盤高於此前 20 日高點 **{breakouts} 檔**（僅計入正常且已驗證結果）。共同分析日：**{', '.join(common_dates) if common_dates else as_of}**。",
        "",
        "| 股票全名（代號） | 資料日 | 交易狀態 | K線根數 | 收盤 | 63日報酬 | ADR20 | 50日均成交額 | 高於SMA200 | 最窄整固 | 距前20日高點 | 收盤突破 | EMA三線均距 | 核心條件 | 未驗證項目 | 驗證註記 | 未通過條件 |",
        "|---|---|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---:|:---:|---|---|---|",
    ]
    for r in rows:
        close = number(r, "close")
        turnover = number(r, "turnover50")
        base_pct = number(r, "best_base_pct")
        base_days = number(r, "best_base_days")
        emad = number(r, "ema_mean_distance_pct")
        bars = number(r, "bars")
        failures = "、".join(confirmed_failures(r)) or "—"
        breakout = boolean(r, "breakout_close")
        base = "未驗證" if base_pct is None or base_days is None else f"{base_days:.0f}日/{base_pct:.2f}%"
        suspended_row = not eligible(r)
        historical_close = number(r, "historical_close")
        close_text = (f"歷史 ${historical_close:.2f}" if suspended_row and historical_close is not None else "未驗證") if suspended_row else ("未驗證" if close is None else f"${close:.2f}")
        bars_text = "未驗證" if bars is None else f"{bars:.0f}根"
        unknown = "；".join(unverified_conditions(r)) or "—"
        note = validation_note(r)
        lines.append(
            f"| {r.get('name', '')} ({r['code']}) | {display_date(r.get('date'))} | {'停牌' if suspended_row else '正常'} | {bars_text} | {close_text} | "
            f"{pct(number(r, 'return_63_pct'), True)} | {pct(number(r, 'adr20_pct'))} | "
            f"{'未驗證' if turnover is None else f'${turnover / 1e6:.1f}m'} | "
            f"{sma200_text(r)} | {base} | {pct(number(r, 'trigger_gap_pct'), True)} | "
            f"{'是' if breakout is True else '否' if breakout is False else '未驗證'} | {pct(emad)} | {core_label(r)} | {unknown} | {note} | {failures} |"
        )
    lines.extend([
        "",
        f"**篩選及資料說明：** 候選池由本輪 Futu 螢幕動態產生，寬鬆預篩為市值>$5bn、股價>$5、60日回報≥18%（涵蓋 63 日目標的預篩緩衝）、50日均成交額>$5m、20日平均振幅≥3%；最後依 K 線精算 63日回報≥20%、ADR20>3.5%、整固5–39日且幅度<8%、收盤不低於前20日低點、SMA200上方幅度≤60%。未達各項歷史樣本數者顯示「未驗證」，不以較短歷史代替，亦不計入完整核心通過；63日報酬須64根、50日均成交額須50根且資料完整、SMA200須200根、整固至少5根、前20日高低點需21根。EMA10／20／50供排序，ADR20不是 Wilder ATR。這是依 Futu 預篩條件動態挑出的候選池，不是固定 53 檔，也不代表對所有市值>$5bn股票逐一抓取日線；收盤越過前高僅是價位事件，未確認成交量或後續延續。",
        "",
    ])
    if dashboard_url:
        lines.append(f"[開啟互動式 EMA／突破／回踩 dashboard]({dashboard_url})")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metrics", required=True)
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    ap.add_argument("--expected-count", type=int, help="Optional exact row count; omit for a dynamic universe")
    ap.add_argument("--output", help="Write Markdown to this path; otherwise print to stdout")
    ap.add_argument("--dashboard-url", default="", help="Optional public dashboard URL")
    ap.add_argument("--screen-summary", help="JSON summary written by prepare_dynamic_universe.py")
    args = ap.parse_args()
    with open(args.metrics, newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    summary = json.loads(Path(args.screen_summary).read_text(encoding="utf-8")) if args.screen_summary else None
    report = render(rows, args.as_of, args.expected_count, args.dashboard_url, summary)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        print(f"Report: {path}")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
