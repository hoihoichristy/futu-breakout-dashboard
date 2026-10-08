"""Read reviewed symbol-specific history thresholds; do not fabricate long-lookback metrics."""
import json
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parent.parent / 'validation_policy.json'

def minimum_bars(symbol, fallback=200):
    policy = json.loads(POLICY_PATH.read_text(encoding='utf-8')) if POLICY_PATH.exists() else {}
    base = int(policy.get('default_min_bars', fallback))
    value = int(policy.get('symbol_min_bars', {}).get(symbol, base))
    if base != 200 or value < 64 or value > base:
        raise ValueError('Invalid history policy: default must be 200, per-symbol minimum must be 64–200')
    return value
