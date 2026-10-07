# Daily Futu refresh runbook

This runbook is executed by the Manus after-close schedule, not by a GitHub Actions runner. The schedule has the Futu and GitHub connectors attached. **Refresh only the existing 53 reviewed symbols** in `universe.csv`; do not imply that the full U.S. market is being rescanned or add new symbols.

## 1. Prepare a clean capture directory

From the repository root (`/home/ubuntu/futu-breakout-dashboard-deploy`), create a unique run directory and private log:

```bash
scripts/start_daily_run.sh /home/ubuntu/futu-breakout-dashboard-deploy
. /tmp/futu-refresh-current.state
FUTU_REPO_URL="https://github.com/hoihoichristy/futu-breakout-dashboard"
FUTU_PAGES_URL="https://hoihoichristy.github.io/futu-breakout-dashboard/"
FUTU_BRANCH=main
printf 'state=%s\nlog=%s\n' "$STATE_PATH" "$LOG_PATH"
```

At the start of each later shell invocation, recover these values with `. /tmp/futu-refresh-current.state`. Read the 53 `code` values from `universe.csv`; confirm there are exactly 53 unique codes. Set `END_DATE` to the current calendar date in `America/New_York` (at 06:00 Asia/Hong_Kong, the prior U.S. session has closed):

```bash
END_DATE=$(python3 -c 'from datetime import datetime; from zoneinfo import ZoneInfo; print(datetime.now(ZoneInfo("America/New_York")).date())')
printf '[run] end_date=%s universe=53\n' "$END_DATE" | tee -a "$LOG_PATH"
```

The human-readable per-run log and retained CSV/Markdown outputs live under `repo/.runlogs/<UTC-run-tag>/`; this directory is ignored by Git and must not be published. Raw captured Futu JSON is under the run's `/tmp/futu-refresh-<UTC-run-tag>/` directory. MCP tool-result JSON is normally saved under `/home/ubuntu/.mcp/tool-results/` in this Sandbox; use an exact result path returned by the tool when available.

## 2. Fetch and capture each symbol sequentially

For **each** code, make one Futu `quote_history_kline` call with:

- `symbol`: the exact `code` from `universe.csv` (for example `US.MSFT`)
- `end`: current date in `America/New_York`, formatted `YYYY-MM-DD`
- `ktype`: `2` (daily)
- `autype`: `1` (forward-adjusted)
- `extended_time`: `0` (regular daily bars)
- `num`: `210` (the tool maximum is 370; 210 is enough for the 200-day average plus warm-up)

Keep these calls **sequential**. Immediately after each successful tool call, save its fresh JSON result before requesting the next symbol:

```bash
SYMBOL='US.SYMBOL'
printf '[fetch] %s end=%s\n' "$SYMBOL" "$END_DATE" >> "$LOG_PATH"
python3 scripts/capture_latest_futu_result.py \
  --symbol "$SYMBOL" --started-epoch "$STARTED_EPOCH" --raw-dir "$RAW_DIR" \
  >> "$LOG_PATH" 2>&1
```

If the tool response gives an exact saved result path, add `--source-file '/path/from/result.json'`. The helper rejects results created before this run, duplicate result files, API errors, and histories shorter than 200 bars. Do not continue to publish if any symbol call/capture fails.

## 3. Rebuild and validate

```bash
python3 scripts/rebuild_futu_dashboard.py \
  --universe universe.csv --raw-dir "$RAW_DIR" \
  --output "$INDEX_PATH" --metrics-output "$METRICS_PATH" \
  --expected-count 53 2>&1 | tee -a "$LOG_PATH"
```

The rebuild recalculates the same screen metrics and charts from Futu OHLCV; it preserves each symbol's reviewed security class. It refuses to publish unless all 53 files are present, histories are sufficient, the latest bar dates agree, and the class filter still retains all 53. It writes the validated daily table to `metrics.csv`. Use the returned JSON `as_of` value as the publication date, then render the user-facing table:

```bash
python3 scripts/format_daily_report.py \
  --metrics "$METRICS_PATH" --as-of AS_OF_DATE \
  --expected-count 53 --dashboard-url "$FUTU_PAGES_URL" \
  --output "$REPORT_PATH" 2>&1 | tee -a "$LOG_PATH"
```

Replace `AS_OF_DATE` with the returned date. Read `$REPORT_PATH` and include its complete 53-row table in the scheduled result.

## 4. Publish only a validated build

```bash
FUTU_REPO_URL="https://github.com/hoihoichristy/futu-breakout-dashboard" \
FUTU_PAGES_URL="https://hoihoichristy.github.io/futu-breakout-dashboard/" \
FUTU_BRANCH=main FUTU_LOG_PATH="$LOG_PATH" \
  scripts/publish_dashboard.sh "$INDEX_PATH" AS_OF_DATE /home/ubuntu/futu-breakout-dashboard-deploy
```

Replace `AS_OF_DATE` with the `YYYY-MM-DD` value returned by the rebuild. The publisher verifies GitHub authentication and the configured repo, pulls the configured branch fast-forward only, changes only `index.html`, commits/pushes if the HTML changed, and checks whether GitHub Pages serves the new date. A successful push triggers the existing GitHub Pages branch deployment. Append final status and commit hash to `$LOG_PATH`. **Never print or copy authentication tokens into files, prompts, or logs.**

## 5. Report and failure behavior

After a successful build, report to the user in Traditional Chinese and include a compact Markdown table for **all 53 symbols**, sorted with core-condition passes first and then by EMA10/20/50 average absolute distance (ascending). Use columns: full name (symbol), close, 63-session return, ADR20, 50-day average turnover, % above SMA200, tightest base width/days, gap to prior-20-day high, close breakout (yes/no), mean EMA distance, core pass/fail, and failed conditions. Format values clearly (USD and percent). After the table, state the common Futu data date, number passing all core conditions, number whose close is above the prior 20-session high, commit hash if pushed, whether the public page was verified, and link https://hoihoichristy.github.io/futu-breakout-dashboard/. State that the universe is fixed and not a daily full-market rescreen.

On an incomplete/error response, inconsistent dates, missing authentication, or failed build, append the error and symbol/stage to `$LOG_PATH`, leave the live `index.html` untouched, and report the precise blocker. If the push succeeds but Pages does not show the new date within 120 seconds, report “push succeeded; Pages still rebuilding” rather than claiming live verification. Do not make an investment recommendation.
