#!/usr/bin/env python3
"""Recalculate either a fixed reviewed Futu universe or an explicit current-run screen universe."""
import argparse
import csv
import json
import math
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_futu_bars as analyzer
import build_interactive_dashboard as dashboard
from validation_policy import minimum_bars


def normalize_date(value):
    text = str(value).strip().replace('-', '')
    if len(text) < 8 or not text[:8].isdigit():
        raise ValueError(f'Invalid Futu bar date: {value!r}')
    datetime.strptime(text[:8], '%Y%m%d')
    return text[:8]


def load_universe(path, expected=None):
    with open(path, newline='', encoding='utf-8-sig') as stream:
        rows = list(csv.DictReader(stream))
    required = {'code', 'name', 'Futu_security_type', 'US_listing_class'}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f'Universe CSV must contain: {", ".join(sorted(required))}')
    if expected is not None and len(rows) != expected:
        raise ValueError(f'Expected {expected} reviewed symbols; universe has {len(rows)}')
    codes = [r['code'].strip() for r in rows]
    if len(set(codes)) != len(codes):
        raise ValueError('Duplicate symbol codes in universe CSV')
    return [{k: (r.get(k) or '').strip() for k in required} for r in rows]


def load_symbol_bars(raw_dir, symbol, min_bars):
    path = Path(raw_dir) / f'{symbol}.json'
    if not path.is_file():
        raise ValueError(f'Missing fresh Futu result for {symbol}: {path}')
    payload = json.loads(path.read_text(encoding='utf-8'))
    if payload.get('ret_code', 0) not in (0, '0', None):
        raise ValueError(f'Futu error for {symbol}: {payload.get("ret_msg", "")}')
    bars = payload.get('data', {}).get('kline_list', [])
    if len(bars) < min_bars:
        raise ValueError(f'{symbol}: got {len(bars)} bars; need at least {min_bars}')
    by_date = {normalize_date(b['date']): b for b in bars}
    bars = [by_date[d] for d in sorted(by_date)]
    for bar in bars:
        prices = {field: float(bar[field]) for field in ('open', 'high', 'low', 'close')}
        if not all(math.isfinite(v) and v > 0 for v in prices.values()):
            raise ValueError(f'{symbol}: invalid OHLC on {bar["date"]}')
        if prices['high'] < prices['low']:
            raise ValueError(f'{symbol}: high below low on {bar["date"]}')
    if len(bars) < min_bars:
        raise ValueError(f'{symbol}: only {len(bars)} unique dated bars')
    return bars, normalize_date(bars[-1]['date'])


def verified_suspensions(universe, status_file=None, started_epoch=None):
    policy_path = HERE.parent / 'validation_policy.json'
    policy = json.loads(policy_path.read_text(encoding='utf-8')) if policy_path.exists() else {}
    reviewed = {row['code'] for row in universe}
    allowed = set(policy.get('suspension_date_exceptions', [])) & reviewed
    if not allowed:
        return {}
    if policy.get('scope') != 'reviewed_universe' or not policy.get('suspension_evidence_required'):
        raise ValueError('Suspension exceptions require reviewed scope and fresh evidence')
    if not status_file or started_epoch is None or not math.isfinite(started_epoch):
        raise ValueError('This universe requires --quote-status-file and --started-epoch')
    path = Path(status_file)
    evidence = json.loads(path.read_text(encoding='utf-8'))
    epoch = float(evidence.get('captured_epoch', 0))
    if (path.stat().st_mtime < started_epoch or not math.isfinite(epoch)
            or epoch < started_epoch or epoch > time.time() + 60):
        raise ValueError('Suspension evidence is stale or outside this run')
    code = evidence.get('code')
    if (evidence.get('source') != 'Futu quote_stock_quote' or evidence.get('ret_code') != 0
            or code not in allowed or allowed != {code}):
        raise ValueError('Missing successful Futu evidence for authorized suspension code')
    status, suspended = evidence.get('sec_status'), evidence.get('suspension')
    if status == 'SUSPENDED' and suspended is True:
        normalize_date(evidence['data_date'])
        return {code: evidence}
    if suspended is False and status and status != 'SUSPENDED':
        return {}  # Trading resumed: normal common-date validation applies again.
    raise ValueError('Ambiguous Futu suspension status; do not waive date validation')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--universe', required=True)
    ap.add_argument('--raw-dir', required=True)
    ap.add_argument('--output', required=True, help='Temporary output, not the live repo file')
    ap.add_argument('--expected-count', type=int, help='Optional expected count; omit to infer the input CSV size')
    ap.add_argument('--min-bars', type=int, default=200)
    ap.add_argument('--dynamic-screen', action='store_true',
                    help='Allow the run-specific Futu-screened universe; insufficient metrics remain unverified')
    ap.add_argument('--metrics-output', help='Optional validated metrics CSV')
    ap.add_argument('--quote-status-file', help="This run's captured Futu QMMM quote status")
    ap.add_argument('--started-epoch', type=float, help='Run start for status freshness checks')
    args = ap.parse_args()

    universe = load_universe(args.universe, args.expected_count)
    expected_count = len(universe)
    suspensions = verified_suspensions(universe, args.quote_status_file, args.started_epoch)
    rows, bars_by_code, latest_dates = [], {}, {}
    for meta in universe:
        if args.dynamic_screen:
            # The input universe must be the output of prepare_dynamic_universe.py for this run.
            required_bars = max(1, args.min_bars)
        else:
            required_bars = minimum_bars(meta['code'], args.min_bars)
        bars, latest_date = load_symbol_bars(args.raw_dir, meta['code'], required_bars)
        latest_dates[meta['code']] = latest_date
        row = analyzer.analyze(meta['name'], bars)
        row.update({
            'code': meta['code'], 'Futu_security_type': meta['Futu_security_type'],
            'US_listing_class': meta['US_listing_class'], 'market_status': 'ACTIVE',
            'metric_eligible': True, 'historical_close': None, 'analysis_date': '',
            'ema_mean_distance_pct': None,
            'core_status': 'pass' if row['pass_core'] else 'fail',
            'unverified_conditions': '', 'validation_note': '',
        })
        indicator_labels = {
            'return_63_pct': '63日報酬', 'adr20_pct': 'ADR20', 'turnover50': '50日均成交額',
            'above_sma200_pct': 'SMA200', 'best_base_pct': '5–39日整固',
            'prior20_high': '前20日高低點／突破', 'ema10': 'EMA10', 'ema20': 'EMA20', 'ema50': 'EMA50',
        }
        missing = [label for field, label in indicator_labels.items() if row.get(field) is None]
        if row['unknown_tests']:
            row['pass_core'] = False
            row['core_status'] = 'unverified'
        if missing:
            row['unverified_conditions'] = '; '.join(missing)
            row['validation_note'] = (f"{meta['code']} 只有 {len(bars)} 根日線；"
                                      f"未驗證：{'、'.join(missing)}；不縮短指標期間，EMA 使用現有歷史種子。")
        if meta['code'] in suspensions:
            proof = suspensions[meta['code']]
            if normalize_date(proof['data_date']) != latest_date:
                raise ValueError(f"{meta['code']}: quote and historical last-trade dates differ")
            row['market_status'] = 'SUSPENDED'
            row['metric_eligible'] = False
            row['historical_close'] = row['close']
            for field in set(dashboard.NUMERIC) | {'ema_mean_distance_pct'}:
                if field not in {'bars', 'historical_close'}:
                    row[field] = None
            row['above_prior20_low'] = row['breakout_close'] = None
            row['pass_core'] = False
            row['core_status'] = 'unverified'
            row['failures'] = []
            row['unknown_tests'] = list(dashboard.CORE_FAILURE_KEYS)
            row['unverified_conditions'] = '停牌：所有當前指標'
            historical_date = datetime.strptime(latest_date, '%Y%m%d').strftime('%Y-%m-%d')
            row['validation_note'] = (f'Futu 本輪確認停牌；歷史日線截至 {historical_date}。'
                                      '舊 K 線保留，所有當前指標未驗證；不計入核心／突破統計及 EMA 排名。')
        rows.append(row)
        bars_by_code[meta['code']] = [{
            'date': normalize_date(b['date']), 'open': float(b['open']),
            'high': float(b['high']), 'low': float(b['low']), 'close': float(b['close']),
        } for b in bars]

    active_dates = {code: date for code, date in latest_dates.items() if code not in suspensions}
    if not active_dates or len(set(active_dates.values())) != 1:
        counts = Counter(active_dates.values())
        raise ValueError('Latest normal-trading dates differ; refusing stale publish: ' +
                         ', '.join(f'{d} ({n} symbols)' for d, n in sorted(counts.items())))
    common_date = next(iter(set(active_dates.values())))
    for row in rows:
        if latest_dates[row['code']] > common_date:
            raise ValueError(f"{row['code']}: historical date newer than active common date")
        row['analysis_date'] = common_date

    with tempfile.NamedTemporaryFile('w', newline='', encoding='utf-8-sig', suffix='.csv') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        stream.flush()
        checked_rows, excluded = dashboard.load_metrics(stream.name, common_adr_only=True)
    if excluded or len(checked_rows) != expected_count:
        raise ValueError(f'Security-class validation changed universe: kept={len(checked_rows)}, expected={expected_count}, excluded={len(excluded)}')

    if args.metrics_output:
        metrics_path = Path(args.metrics_output)
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        with metrics_path.open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(checked_rows[0].keys()))
            writer.writeheader()
            for checked in checked_rows:
                item = dict(checked)
                item['failures'] = '; '.join(next(r['failures'] for r in rows if r['code'] == item['code']))
                item['rules'] = '; '.join('unverified' if v is None else 'pass' if v else 'fail' for v in item.get('rules', []))
                writer.writerow(item)

    as_of = datetime.strptime(common_date, '%Y%m%d').strftime('%Y-%m-%d')
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    html = dashboard.build_html(checked_rows, bars_by_code,
                                'Futu 美股普通股與 ADR｜互動式突破／回踩儀表板', as_of)
    out.write_text(html, encoding='utf-8')
    if 'const D=' not in html or 'const B=' not in html:
        out.unlink(missing_ok=True)
        raise ValueError('Generated dashboard failed structural validation')
    print(json.dumps({
        'status': 'built', 'as_of': as_of, 'symbols': len(checked_rows),
        'core_pass': sum(bool(r['pass_core']) for r in checked_rows),
        'price_breakouts': sum(bool(r['breakout_close']) for r in checked_rows),
        'unverified_symbols': [r['code'] for r in checked_rows if r.get('core_status') == 'unverified'],
        'active_symbols': len(active_dates), 'suspended_symbols': list(suspensions),
        'historical_dates': {code: latest_dates[code] for code in suspensions},
        'bars_per_symbol_min': min(len(v) for v in bars_by_code.values()),
        'output': str(out), 'metrics_output': args.metrics_output,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
