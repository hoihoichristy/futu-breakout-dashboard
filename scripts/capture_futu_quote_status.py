#!/usr/bin/env python3
"""Capture a fresh single-symbol Futu quote as private suspension evidence."""
import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path


def capture(source_file, symbol, started_epoch, output):
    source = Path(source_file)
    if not source.is_file() or source.stat().st_mtime < started_epoch:
        raise ValueError('Quote evidence is missing or predates this run')
    payload = json.loads(source.read_text(encoding='utf-8'))
    if payload.get('ret_code') not in (0, '0'):
        raise ValueError(f'Futu quote failed: {payload.get("ret_msg", "unknown error")}')
    matches = [q for q in payload.get('data', {}).get('quote_list', []) if q.get('code') == symbol]
    if len(matches) != 1:
        raise ValueError(f'Expected exactly one quote for {symbol}')
    quote = matches[0]
    if not isinstance(quote.get('suspension'), bool):
        raise ValueError('Futu suspension flag is missing/ambiguous')
    status = str(quote.get('sec_status') or '').upper()
    if not status or (status == 'SUSPENDED') != quote['suspension']:
        raise ValueError('Futu security status contradicts suspension flag')
    compact_date = str(quote.get('data_date', '')).replace('-', '')
    date = datetime.strptime(compact_date, '%Y%m%d').strftime('%Y-%m-%d')
    last = float(quote['last_price'])
    if not math.isfinite(last) or last <= 0:
        raise ValueError('Invalid historical quote price')
    result = {
        'source': 'Futu quote_stock_quote', 'source_file': source.name,
        'captured_epoch': time.time(),
        'observed_at_utc': datetime.now(timezone.utc).isoformat(),
        'ret_code': 0, 'code': symbol, 'name': quote.get('name', symbol),
        'sec_status': status, 'suspension': quote['suspension'],
        'data_date': date, 'last_price': last,
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Captured quote status: {symbol} {status}; last trade date={date}; evidence={path}')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-file', required=True)
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--started-epoch', type=float, required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    capture(args.source_file, args.symbol, args.started_epoch, args.output)


if __name__ == '__main__':
    main()
