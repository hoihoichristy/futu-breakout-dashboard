#!/usr/bin/env python3
"""Build this run's variable-size U.S. common/ADR universe from fresh Futu screen/basic-info JSON."""
import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

# Futu screen factors are returned as raw integers; values are scaled by 1,000.
SCALES = {2301: 1000, 2201: 1000, 3102: 1000, 3105: 1000, 3103: 1000}
REQUIRED = {2301: 'market_cap', 2201: 'last_price', 3102: 'change_60d',
            3105: 'turnover_50d', 3103: 'amplitude_20d'}
EXPECTED_DAYS = {3102: 60, 3105: 50, 3103: 20}
EXPECTED_AVERAGE = {3102: False, 3105: True, 3103: True}
EXCLUDED_CLASS = re.compile(
    r'\b(PFD|PRF|PREF(?:ERRED)?|PREFERENCE|CDI|ETF|FUND|WARRANTS?|RIGHTS?|'
    r'UNITS?|DEBENTURES?|NOTES?|LTD PARTNERSHIP|LIMITED PARTNERSHIP)\b', re.I)
ADR_CLASS = re.compile(r'\b(ADR|ADS|DEPOSITARY|DEPOSITORY)\b', re.I)


def values_from_item(item):
    out = {}
    for entry in item.get('results', []):
        for kind in ('simple_property_result', 'cumulative_property_result'):
            obj = entry.get(kind)
            if not obj:
                continue
            prop = obj.get('property', {})
            fid = prop.get('name')
            if fid in REQUIRED:
                raw = (obj.get('res') or {}).get('ival', obj.get('value'))
                if raw is None:
                    raw = obj.get('value')
                try:
                    out[fid] = float(raw) / SCALES[fid]
                except (TypeError, ValueError):
                    raise ValueError(f"{item.get('code')}: missing/invalid Futu factor {fid}")
                out[f'{fid}_days'] = prop.get('days')
                out[f'{fid}_average'] = prop.get('period_average')
                if fid in EXPECTED_DAYS and int(prop.get('days', -1)) != EXPECTED_DAYS[fid]:
                    raise ValueError(f"{item.get('code')}: factor {fid} has unexpected lookback {prop.get('days')}")
                if fid in EXPECTED_AVERAGE:
                    actual = prop.get('period_average')
                    if actual is None or bool(int(actual)) != EXPECTED_AVERAGE[fid]:
                        raise ValueError(f"{item.get('code')}: factor {fid} has unexpected averaging mode {actual}")
    missing = set(REQUIRED) - set(out)
    if missing:
        raise ValueError(f"{item.get('code')}: result misses requested factors {sorted(missing)}")
    return out


def load_screens(paths):
    rows, totals, cursors = {}, set(), set()
    summaries = []
    for index, path in enumerate(paths):
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
        if payload.get('ret_code') not in (0, '0'):
            raise ValueError(f'{path}: Futu screener error {payload.get("ret_code")}: {payload.get("ret_msg")}')
        items = payload.get('data', {}).get('items')
        if not isinstance(items, list):
            raise ValueError(f'{path}: missing data.items')
        page = payload.get('pagination') or {}
        if 'total' not in page or 'has_more' not in page:
            raise ValueError(f'{path}: incomplete Futu pagination metadata')
        totals.add(int(page['total']))
        if bool(page['has_more']):
            cursor = str(page.get('next_key') or '')
            if not cursor or cursor in cursors:
                raise ValueError(f'{path}: missing/repeated next_key; do not publish a partial screen')
            cursors.add(cursor)
        elif index != len(paths) - 1:
            raise ValueError(f'{path}: page says no more results but additional page files were supplied')
        for item in items:
            code, name = str(item.get('code') or ''), str(item.get('name') or '')
            if not code.startswith('US.') or not name:
                raise ValueError(f'{path}: non-US/missing code or name: {code!r}')
            if code in rows:
                raise ValueError(f'{path}: duplicate screener code {code}; verify cursor flow')
            factors = values_from_item(item)
            # Recheck the permissive screen thresholds; final 63-day/ADR20 tests use K-lines.
            if not (factors[2301] > 5_000_000_000 and factors[2201] > 5.0
                    and factors[3102] >= 18.0 and factors[3105] > 5_000_000
                    and factors[3103] >= 3.0):
                raise ValueError(f'{code}: returned Futu factors do not satisfy the declared prefilter')
            rows[code] = {'code': code, 'name': name, 'factors': factors}
        summaries.append({'path': Path(path).name, 'items': len(items),
                          'has_more': bool(page['has_more']), 'next_key': page.get('next_key')})
    if len(totals) != 1:
        raise ValueError(f'Futu screener page totals disagree: {sorted(totals)}')
    expected = next(iter(totals))
    if sum(x['items'] for x in summaries) != expected:
        raise ValueError(f'Incomplete Futu screen pages: captured={sum(x["items"] for x in summaries)} total={expected}')
    return rows, summaries, expected


def load_basicinfo(paths):
    found = {}
    for path in paths:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
        if payload.get('ret_code') not in (0, '0'):
            raise ValueError(f'{path}: Futu basicinfo error {payload.get("ret_code")}: {payload.get("ret_msg")}')
        items = payload.get('data', {}).get('basic_list')
        if not isinstance(items, list):
            raise ValueError(f'{path}: missing data.basic_list')
        for item in items:
            code = str(item.get('code') or '')
            if code in found:
                raise ValueError(f'{path}: duplicate basicinfo symbol {code}')
            found[code] = item
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screen-json', action='append', required=True, help='Each fresh quote_stock_screen page; repeat in cursor order')
    parser.add_argument('--basicinfo-json', action='append', required=True, help='Fresh quote_stock_basicinfo responses; repeat for each <=400-symbol batch')
    parser.add_argument('--output-universe', required=True)
    parser.add_argument('--output-excluded', required=True)
    parser.add_argument('--output-summary', required=True)
    parser.add_argument('--end-date', required=True)
    args = parser.parse_args()
    candidates, pages, screened_total = load_screens(args.screen_json)
    basic = load_basicinfo(args.basicinfo_json)
    missing = sorted(set(candidates) - set(basic))
    if missing:
        raise ValueError(f'No Futu basicinfo for screen symbols; do not assume their class: {missing[:20]}')
    extra = sorted(set(basic) - set(candidates))
    if extra:
        raise ValueError(f'Basicinfo contains symbols outside this run\'s Futu screen: {extra[:20]}')
    eligible, excluded = [], []
    for code, candidate in candidates.items():
        item = basic[code]
        instrument = str(item.get('stock_type', item.get('instrument_type', ''))).upper()
        name = candidate['name']
        reason = ''
        if instrument != 'STOCK':
            reason = f'Futu instrument type {instrument or "unknown"} (not STOCK)'
        elif str(item.get('suspension', '')).strip().lower() in ('true', '1', 'yes') and code != 'US.QMMM':
            reason = 'Futu basicinfo marks this symbol suspended; no current technical analysis'
        elif EXCLUDED_CLASS.search(name):
            reason = 'Name identifies a non-common/ADR class or fund/derivative'
        elif not code.startswith('US.'):
            reason = 'Not a U.S. listing'
        else:
            listing_class = 'ADR' if ADR_CLASS.search(name) else '普通股'
            # Keep source-data evidence alongside the per-run table, not just a guessed ticker rule.
            eligible.append({
                'code': code, 'name': name, 'Futu_security_type': instrument,
                'US_listing_class': listing_class,
                'class_evidence': 'Futu US listing + STOCK instrument type + Futu security name; explicit non-common tokens excluded',
                'stock_id': item.get('stock_id', ''),
                'suspension': item.get('suspension', ''),
                'market_cap': candidate['factors'][2301], 'last_price': candidate['factors'][2201],
                'change_60d_pct': candidate['factors'][3102],
                'turnover_50d': candidate['factors'][3105],
                'amplitude_20d_pct': candidate['factors'][3103],
                'analysis_date': args.end_date,
            })
        if reason:
            excluded.append({'code': code, 'name': name, 'instrument_type': instrument, 'reason': reason})
    universe_path = Path(args.output_universe)
    excluded_path = Path(args.output_excluded)
    summary_path = Path(args.output_summary)
    for path in (universe_path, excluded_path, summary_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    fields = ['code', 'name', 'Futu_security_type', 'US_listing_class', 'class_evidence',
              'stock_id', 'suspension', 'market_cap', 'last_price', 'change_60d_pct',
              'turnover_50d', 'amplitude_20d_pct', 'analysis_date']
    with universe_path.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(eligible)
    with excluded_path.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=['code', 'name', 'instrument_type', 'reason'])
        writer.writeheader(); writer.writerows(excluded)
    summary = {
        'status': 'prepared', 'end_date': args.end_date, 'screener_total': screened_total,
        'screen_pages': pages, 'basicinfo_count': len(basic), 'eligible_symbols': len(eligible),
        'excluded_count': len(excluded), 'excluded_by_reason': dict(Counter(r['reason'] for r in excluded)),
        'prefilter': {'market_cap_usd_gt': 5_000_000_000, 'last_price_usd_gt': 5,
                      'Futu_change_60d_pct_gte': 18, 'final_exact_return_63d_gte': 20,
                      'avg_turnover_50d_usd_gt': 5_000_000,
                      'Futu_avg_amplitude_20d_pct_gte': 3,
                      'final_exact_ADR20_pct_gt': 3.5},
        'universe_csv': str(universe_path), 'excluded_csv': str(excluded_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    if not eligible:
        raise SystemExit('No common-stock/ADR screen candidates remain after type filtering; preserve the existing published page.')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
