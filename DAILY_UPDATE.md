# Daily Futu refresh runbook

Run this in Manus with the Futu and GitHub connectors. **Refresh exactly the 53 reviewed common-stock/ADR symbols in `universe.csv`**; never add/remove symbols or claim a full-market scan. Use only Futu market data.

## 1. Private run state

```bash
scripts/start_daily_run.sh /home/ubuntu/futu-breakout-dashboard-deploy
. /tmp/futu-refresh-current.state
FUTU_REPO_URL="https://github.com/hoihoichristy/futu-breakout-dashboard"
FUTU_PAGES_URL="https://hoihoichristy.github.io/futu-breakout-dashboard/"
FUTU_BRANCH=main
END_DATE=$(python3 -c 'from datetime import datetime; from zoneinfo import ZoneInfo; print(datetime.now(ZoneInfo("America/New_York")).date())')
printf '[run] end_date=%s universe=53\n' "$END_DATE" >> "$LOG_PATH"
```

Reload `. /tmp/futu-refresh-current.state` at the start of subsequent shell invocations. Raw results remain under the run's `/tmp/futu-refresh-<UTC-tag>/`; retained logs, metrics and reports are in `.runlogs/<UTC-tag>/` and Git-ignored. Never publish raw results, run logs or credentials.

## 2. Sequential fresh daily bars

For each exact universe code, call Futu `quote_history_kline` sequentially with `symbol=code`, `end=END_DATE`, `ktype=2` (daily), `autype=1` (forward-adjusted), `extended_time=0`, `num=210`. Immediately capture its exact fresh result before the next symbol:

```bash
python3 scripts/capture_latest_futu_result.py \
  --symbol "$SYMBOL" --started-epoch "$STARTED_EPOCH" \
  --raw-dir "$RAW_DIR" --source-file '/exact/result/path/from/tool.json' \
  >> "$LOG_PATH" 2>&1
```

The user authorized **at least one valid unique daily bar** for each fixed reviewed symbol. Missing/invalid OHLC, API failure or an absent symbol still stops publication. Never pad history, shorten indicator definitions or reuse earlier-run results. Use tool calls or individual top-level MCP CLI calls; do not put MCP calls inside Python/subprocess loops.

## 3. Fresh QMMM suspension evidence — every run

The user explicitly authorized a **QMMM-only** date exception on 2026-10-08. It applies only while this run's successful Futu `quote_stock_quote` proves `suspension=true` and `sec_status=SUSPENDED`. Query `code_list=["US.QMMM"]` and capture the exact new result. For example, using the same connector's CLI:

```bash
printf '[quote-status] QMMM\n' >> "$LOG_PATH"
manus-mcp-cli tool call quote_stock_quote --server futu \
  --input '{"code_list":["US.QMMM"]}' > "$RAW_DIR/QMMM.quote.cli.txt" 2>&1
SOURCE_FILE=$(sed -n 's/^Tool execution result saved to: //p' "$RAW_DIR/QMMM.quote.cli.txt" | head -1)
python3 scripts/capture_futu_quote_status.py \
  --symbol US.QMMM --source-file "$SOURCE_FILE" \
  --started-epoch "$STARTED_EPOCH" --output "$RUN_DIR/QMMM_status.json" \
  >> "$LOG_PATH" 2>&1
```

If using the MCP tool directly, pass its exact saved result JSON to the same helper. Do not reuse old status evidence. If the status is missing, ambiguous or fails, stop. If QMMM resumes normal trading, the exception ends and its latest bar date must match the other symbols again.

While confirmed suspended, keep the QMMM row and its original historical candles/date. Store its old close as `historical_close`, not a current price. Null **all current technical metrics**, mark core unverified, show no current EMA/trigger lines, and exclude it from current core/breakout statistics, scatter comparisons and EMA/indicator rankings. Do not label unknown conditions as failures. The quote last-trade date must match its historical bar date. No other stale symbol is exempt.

## 4. Rebuild and validate

```bash
set -o pipefail
python3 scripts/rebuild_futu_dashboard.py \
  --universe universe.csv --raw-dir "$RAW_DIR" \
  --output "$INDEX_PATH" --metrics-output "$METRICS_PATH" \
  --expected-count 53 --quote-status-file "$RUN_DIR/QMMM_status.json" \
  --started-epoch "$STARTED_EPOCH" \
  | tee "$RUN_DIR/build_summary.json" | tee -a "$LOG_PATH"
```

All 53 files and reviewed classes must remain. All **normal-trading** symbols must have a common latest date. Only the verified QMMM suspension exception may retain a different old date. Header and report must distinguish the normal common analysis date from QMMM's individual historical date.

Indicator requirements remain unchanged: return63=64 bars; ADR20=20; turnover50=50 and complete turnover; SMA200=200; consolidation=at least 5; prior20 high/low and breakout=21; EMA10/20/50=10/20/50. Missing indicators stay null/unverified. Any unknown core condition means `pass_core=false`; never substitute a short mean for SMA200. Keep known failures separate from unknown conditions.

Use `as_of` from `build_summary.json`, then:

```bash
python3 scripts/format_daily_report.py \
  --metrics "$METRICS_PATH" --as-of AS_OF_DATE --expected-count 53 \
  --dashboard-url "$FUTU_PAGES_URL" --output "$REPORT_PATH" \
  2>&1 | tee -a "$LOG_PATH"
```

## 5. Safe publication

Only after all checks and the full 53-row report succeed:

```bash
FUTU_REPO_URL="https://github.com/hoihoichristy/futu-breakout-dashboard" \
FUTU_PAGES_URL="https://hoihoichristy.github.io/futu-breakout-dashboard/" \
FUTU_BRANCH=main FUTU_LOG_PATH="$LOG_PATH" \
  scripts/publish_dashboard.sh "$INDEX_PATH" AS_OF_DATE /home/ubuntu/futu-breakout-dashboard-deploy
```

Replace `AS_OF_DATE` with the actual returned date. The publisher verifies GitHub authentication/origin, pulls fast-forward only, updates only `index.html`, pushes main and checks the **exact live SHA-256**, not just a date string. Never print/store tokens. A successful push triggers the existing branch-based GitHub Pages deployment.

## 6. Traditional Chinese result and failures

Report the complete 53-row metrics table (core passes first, then mean EMA distance; inactive last), common **normal-trading** date, suspended symbol's separate date, core-pass and breakout counts excluding suspension, unverified normal count, commit hash, verified live content and page URL. Explain that this is a fixed 53-stock refresh, not a full-market rescreen; ADR20 is not Wilder ATR; no personalized investment advice.

Log every fetch/capture/build/report/publish/verification/failure to `LOG_PATH`; retain `run.log`, `metrics.csv`, `report.md` privately. On data/API/class/date/build/auth failure, leave the original live page unchanged and report the precise cause. If push succeeds but content verification times out, report deployment still pending, never claim it was verified. The suspension exception does not authorize other date mismatches or missing market data.
