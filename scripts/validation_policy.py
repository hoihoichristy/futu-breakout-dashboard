"""Use only the authorized reviewed universe's history thresholds; never fabricate SMA200."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / 'validation_policy.json'

def minimum_bars(symbol, fallback=200):
    policy = json.loads(POLICY_PATH.read_text(encoding='utf-8')) if POLICY_PATH.exists() else {}
    base = int(policy.get('default_min_bars', fallback))
    if base < 1 or base > 200:
        raise ValueError('History retention minimum must be 1–200; indicator lookbacks are unchanged')
    if base < 200:
        if policy.get('scope') != 'reviewed_universe':
            raise ValueError('Short-history policy must explicitly restrict its scope to the reviewed universe')
        with (ROOT / 'universe.csv').open(encoding='utf-8-sig', newline='') as f:
            codes = {r['code'].strip() for r in csv.DictReader(f)}
        if symbol not in codes:
            return 200
    value = int(policy.get('symbol_min_bars', {}).get(symbol, base))
    if value < 1 or value > 200:
        raise ValueError('Per-symbol history retention minimum must be 1–200')
    return value
