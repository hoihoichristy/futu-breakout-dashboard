# Daily Futu market-screen and dashboard runbook

Run in Manus with the existing Futu and GitHub connectors. **Every run builds a fresh candidate universe from Futu's U.S. market screener**; do not reuse the former 53-symbol universe as the scan universe and do not invent/append symbols. Only Futu supplies market/screen/K-line data. The old `universe.csv` remains an archival baseline and is not the daily scan input.

## 1. Private run state

At the very beginning:

```bash
cd /home/ubuntu/futu-breakout-dashboard-deploy
scripts/start_daily_run.sh /home/ubuntu/futu-breakout-dashboard-deploy
. /tmp/futu-refresh-current.state
FUTU_PAGES_URL='https://hoihoichristy.github.io/futu-breakout-dashboard/'
FUTU_REPO_URL='https://github.com/hoihoichristy/futu-breakout-dashboard'
FUTU_BRANCH=main
END_DATE=$(python3 -c 'from datetime import datetime; from zoneinfo import ZoneInfo; print(datetime.now(ZoneInfo("America/New_York")).date())')
SCREEN_DIR="$RUN_DIR/screen"
mkdir -p "$SCREEN_DIR"
printf '[start] end_date=%s dynamic_universe=true\n' "$END_DATE" >> "$LOG_PATH"
```

Reload `. /tmp/futu-refresh-current.state` in later shell invocations. Raw screen pages, basic-info results and fresh bars stay in the per-run `/tmp/futu-refresh-<UTC-tag>/`. Retain only `run.log`, `screen_summary.json`, `screen_excluded.csv`, `metrics.csv`, and `report.md` in Git-ignored `.runlogs/<UTC-tag>/`. Never place raw tool payloads, credentials, or tokens in the public repository.

## 2. Fresh paginated U.S. Futu pre-screen

Use Futu `quote_stock_screen`, page size 300, `simple_field_query` market=US (`simple_field=1`, `screen_value_list=[2]`). Apply all these **loose prefilters** (numeric values are Futu raw values scaled by 1,000):

- market cap (`simple_property` 2301) **>$5,000,000,000**: lower value `5000000000000`, `includes=false`;
- last price (2201) **>$5**: lower value `5000`, `includes=false`;
- 60-session return (`cumulative_property` 3102, `days=60`, `period_average=false`) **≥18%**: lower value `18000`, `includes=true`; this is a recall buffer only—final 63-session return must be recomputed from K-lines and be ≥20%;
- 50-session average turnover (3105, `days=50`, `period_average=true`) **>$5,000,000**: lower value `5000000000`, `includes=false`;
- 20-session average amplitude (3103, `days=20`, `period_average=true`) **≥3%**: lower value `3000`, `includes=true`; this is a permissive proxy—final ADR20 must be recomputed from K-lines and be >3.5%.

For each page, retrieve properties in this order: basic 1101/1102; simple 2301/2201; cumulative 3102 (`days=60`, average false), 3105 (`days=50`, average true), and 3103 (`days=20`, average true). Pass back the exact `pagination.next_key` until `has_more=false`; save each exact new JSON result to `$RAW_DIR/screen/page-001.json`, `page-002.json`, etc. Record the full `pagination.total`; missing or duplicate pages are fatal. The `prepare_dynamic_universe.py` helper independently checks page totals, the five returned raw factors/scales, and each row's prefilter values.

Do not make a 53-symbol static request. Use the entire Futu U.S. screen result across all pages. The 18%/3% loosened prefilters deliberately make the K-line stage the final authority for the user's exact thresholds.

## 3. Security-type check and per-run universe

Call Futu `quote_stock_basicinfo` for every unique screen result code, in batches of no more than 400. Save each fresh result JSON under `$RAW_DIR/basicinfo/batch-001.json` etc. Require an exact code-to-result match—missing symbols or failed batches stop publication.

Build the candidate CSV for **this run only**; do not modify the archival `universe.csv`:

```bash
python3 scripts/prepare_dynamic_universe.py \
  --screen-json "$RAW_DIR/screen/page-001.json" \
  --basicinfo-json "$RAW_DIR/basicinfo/batch-001.json" \
  --output-universe "$RUN_DIR/universe.csv" \
  --output-excluded "$RUN_DIR/screen_excluded.csv" \
  --output-summary "$RUN_DIR/screen_summary.json" \
  --end-date "$END_DATE" >> "$LOG_PATH" 2>&1
```

Repeat `--screen-json` / `--basicinfo-json` for every file. Only Futu `stock_type=STOCK` survives; ETF/other Futu instrument types are excluded. The processor classifies a U.S.-listed `STOCK` as ADR when its Futu security name explicitly says ADR/ADS/depositary; it classifies the remaining plain U.S.-listed stock names as ordinary shares, and excludes names explicitly describing preferred/PFD/PRF, CDI, fund, warrant, right, unit, note or debenture classes. Every per-run row keeps the Futu symbol, full name, type, class decision note and screen factors. Any unexpected type/classification pattern should be reviewed and excluded as unverified—not silently treated as an ordinary share. Exclusions and their reasons remain in the private run report.

The existing, expressly approved QMMM suspension exception remains narrow: it applies only when US.QMMM is actually present in the current candidate CSV and a **fresh Futu `quote_stock_quote`** from this run verifies `suspension=true` and `sec_status=SUSPENDED`. If QMMM is present, query and capture its exact new quote:

```bash
manus-mcp-cli tool call quote_stock_quote --server futu \
  --input '{"code_list":["US.QMMM"]}' > "$RAW_DIR/QMMM.quote.cli.txt" 2>&1
SOURCE_FILE=$(sed -n 's/^Tool execution result saved to: //p' "$RAW_DIR/QMMM.quote.cli.txt" | head -1)
python3 scripts/capture_futu_quote_status.py --symbol US.QMMM \
  --source-file "$SOURCE_FILE" --started-epoch "$STARTED_EPOCH" \
  --output "$RUN_DIR/QMMM_status.json" >> "$LOG_PATH" 2>&1
QMMM_STATUS_ARGS="--quote-status-file $RUN_DIR/QMMM_status.json"
```

No other suspended/stale symbol receives a date waiver. The screener/basic-info filter should normally exclude suspended securities; if QMMM is absent, do not make a QMMM quote call and leave `QMMM_STATUS_ARGS` empty.

## 4. Sequential fresh K-lines and capture

For each code in the generated `$RUN_DIR/universe.csv`, in order, call Futu `quote_history_kline(symbol=code, end=END_DATE, num=210)`. Omit optional enums so the connector defaults apply: daily K-lines, forward-adjusted prices, normal session (not extended). Immediately copy the exact fresh tool-result JSON path into the helper before starting the next symbol:

```bash
python3 scripts/capture_latest_futu_result.py \
  --symbol "$SYMBOL" --started-epoch "$STARTED_EPOCH" \
  --raw-dir "$RAW_DIR/bars" --screened-universe "$RUN_DIR/universe.csv" \
  --dynamic-screen --min-bars 1 --source-file '/exact/new/tool-result.json' \
  >> "$LOG_PATH" 2>&1
```

The dynamic flag is valid only for symbols in this run's generated screen CSV. One or more valid bars may be retained, but missing indicator histories stay null/“未驗證”; they never count as complete matches. A missing result, API error, invalid OHLC or capture failure stops the update. Never reuse prior-run results, backfill fabricated prices, shorten lookbacks, or run MCP calls inside a shell/Python loop.

## 5. Rebuild, exact rules and consistency checks

```bash
N=$(python3 -c 'import csv,sys; print(sum(1 for _ in csv.DictReader(open(sys.argv[1],encoding="utf-8-sig"))))' "$RUN_DIR/universe.csv")
set -o pipefail
python3 scripts/rebuild_futu_dashboard.py \
  --universe "$RUN_DIR/universe.csv" --raw-dir "$RAW_DIR/bars" \
  --output "$INDEX_PATH" --metrics-output "$METRICS_PATH" \
  --expected-count "$N" --dynamic-screen --min-bars 1 \
  ${QMMM_STATUS_ARGS:-} --started-epoch "$STARTED_EPOCH" \
  | tee "$RUN_DIR/build_summary.json" | tee -a "$LOG_PATH"
```

The rebuild recomputes every exact user condition, not just the prefilter: 63-session return ≥20%; close>$5; 50-session average dollar turnover>$5m; ADR20>3.5%; price no more than 60% above SMA200; a 5–39-session consolidation with range<8%; and close not below the prior 20-session low. It also calculates EMA10/20/50 distances for ranking and records whether the latest close is above the prior 20-session high. Keep strict lookbacks: 63-day return requires 64 bars, ADR20 20, turnover50 50 complete values, SMA200 200, consolidation at least 5, prior 20-session levels 21, and EMA10/20/50 their respective periods. A short-history row is visible as unverified; never substitute a shorter SMA200 or call it a match.

All active symbols must have valid fresh K-lines and the same latest normal-trading session date. A mixed/old date, missing symbol or ambiguous QMMM status stops publication; the existing live page must remain unchanged. If QMMM is present and fresh suspension proof is supplied, preserve its old candles/date, null all current metrics, and exclude it from current pass/breakout/EMA statistics. No stale-data exception applies to another symbol.

## 6. Complete report and safe publication

Use the actual `as_of` date and count from `build_summary.json`:

```bash
AS_OF=$(python3 -c 'import json; print(json.load(open("'$RUN_DIR'/build_summary.json"))["as_of"])')
python3 scripts/format_daily_report.py \
  --metrics "$METRICS_PATH" --as-of "$AS_OF" --expected-count "$N" \
  --screen-summary "$RUN_DIR/screen_summary.json" \
  --dashboard-url "$FUTU_PAGES_URL" --output "$REPORT_PATH" \
  2>&1 | tee -a "$LOG_PATH"
```

Before publishing, sync core-condition passes to the existing Futu watchlist group **`Watchlist US 02`** (the visible group corresponding to the requested Watchlist 02). Include only rows whose `core_status` is exactly `pass`; exclude failed and unverified rows. Use the exact Futu `code` values from this run's validated `$METRICS_PATH`, not names or guessed tickers. First query `quote_user_security(group_name="Watchlist US 02")`; compare codes and call `quote_modify_user_security(op="ADD", group_name="Watchlist US 02", code_list=[...])` only for missing symbols. Split into batches of at most 200 codes. This is additive only: never delete, move, or remove existing watchlist entries. If there are no passing symbols or no missing codes, log that no addition was needed. Record the pass count, already-present count, newly-added count, exact group name, and tool result in `LOG_PATH`. A watchlist query/add error stops publication and must be reported; do not claim a successful sync without a successful Futu response.

Only after all dynamically screened symbols are accounted for, security types are checked, the exact metrics build succeeds, and the full variable-size Traditional Chinese table succeeds, run:

```bash
FUTU_REPO_URL="$FUTU_REPO_URL" FUTU_PAGES_URL="$FUTU_PAGES_URL" \
FUTU_BRANCH=main FUTU_LOG_PATH="$LOG_PATH" \
  scripts/publish_dashboard.sh "$INDEX_PATH" "$AS_OF" /home/ubuntu/futu-breakout-dashboard-deploy
```

The publisher updates only `index.html`, pushes to the existing GitHub Pages repository, and verifies the exact live HTML SHA-256. It must not push run logs, raw tool results, universe CSVs, credentials, or tokens. Record the resulting commit hash and whether the live hash/date was verified. A successful push without live verification is “部署中,” not complete.

Report in Traditional Chinese: the screener's total and pages, number retained for analysis, securities excluded and reasons, the full metrics table ordered core-pass first then average EMA distance, common data date, core pass count, close-above-prior-20-high count, Watchlist US 02 new-addition and already-present counts, live-page verification, commit hash and URL. Clarify that the daily candidate set is selected by this dynamic Futu screen (not all >$5bn stocks have K-lines fetched), and that 60-day return / average amplitude were loose prefilters while exact 63-day return / ADR20 were recalculated. ADR20 is not Wilder ATR; no personalized investment advice.

Log every screen page, basic-info batch, bar capture, build, report, publication and failure to `LOG_PATH`. Any error leaves the old live page unchanged and must identify the failed stage/symbol and current private log path.
