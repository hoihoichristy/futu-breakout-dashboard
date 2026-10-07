# Daily Futu refresh runbook

This runbook is executed by the Manus after-close schedule, not by a GitHub Actions runner. The schedule has the Futu and GitHub connectors attached. **Refresh only the existing 53 reviewed symbols** in `universe.csv`; do not imply that the full U.S. market is being rescanned or add new symbols.

## 1. Prepare a clean capture directory

From the repository root (`/home/ubuntu/futu-breakout-dashboard-deploy`):

```bash
RUN_TAG=$(date -u +%Y%m%dT%H%M%SZ)
STARTED_EPOCH=$(date +%s)
RAW_DIR="/tmp/futu-refresh-${RUN_TAG}"
mkdir -p "$RAW_DIR"
printf '%s\n%s\n' "$STARTED_EPOCH" "$RAW_DIR" > /tmp/futu-refresh-current.txt
```

Read the 53 `code` values from `universe.csv`. Confirm there are exactly 53 unique codes. Determine the current calendar date in `America/New_York` and use it as Futu's inclusive `end` date; the schedule fires at 06:00 Asia/Hong_Kong, after the preceding U.S. close.

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
python3 scripts/capture_latest_futu_result.py \
  --symbol 'US.SYMBOL' --started-epoch "$STARTED_EPOCH" --raw-dir "$RAW_DIR"
```

If the tool response gives an exact saved result path, add `--source-file '/path/from/result.json'`. The helper rejects results created before this run, duplicate result files, API errors, and histories shorter than 200 bars. Do not continue to publish if any symbol call/capture fails.

## 3. Rebuild and validate

```bash
python3 scripts/rebuild_futu_dashboard.py \
  --universe universe.csv --raw-dir "$RAW_DIR" \
  --output "$RAW_DIR/index.html" --metrics-output "$RAW_DIR/metrics.csv" \
  --expected-count 53
```

The rebuild recalculates the same screen metrics and charts from Futu OHLCV; it preserves each symbol's reviewed security class. It refuses to publish unless all 53 files are present, histories are sufficient, the latest bar dates agree, and the class filter still retains all 53. It writes the validated daily table to `metrics.csv`. Use the returned JSON `as_of` value as the publication date, then render the user-facing table:

```bash
python3 scripts/format_daily_report.py \
  --metrics "$RAW_DIR/metrics.csv" --as-of AS_OF_DATE \
  --expected-count 53 --output "$RAW_DIR/report.md"
```

Replace `AS_OF_DATE` with the returned date. Read `report.md` and include its complete 53-row table in the scheduled result.

## 4. Publish only a validated build

```bash
scripts/publish_dashboard.sh "$RAW_DIR/index.html" AS_OF_DATE /home/ubuntu/futu-breakout-dashboard-deploy
```

Replace `AS_OF_DATE` with the `YYYY-MM-DD` value returned by the rebuild. The publisher verifies GitHub authentication and the expected repo, pulls `main` fast-forward only, changes only `index.html`, commits/pushes if the HTML changed, and checks whether GitHub Pages serves the new date. A successful push triggers the existing GitHub Pages branch deployment. **Never print or copy authentication tokens into files, prompts, or logs.**

## 5. Report and failure behavior

After a successful build, report to the user in Traditional Chinese and include a compact Markdown table for **all 53 symbols**, sorted with core-condition passes first and then by EMA10/20/50 average absolute distance (ascending). Use columns: full name (symbol), close, 63-session return, ADR20, 50-day average turnover, % above SMA200, tightest base width/days, gap to prior-20-day high, close breakout (yes/no), mean EMA distance, core pass/fail, and failed conditions. Format values clearly (USD and percent). After the table, state the common Futu data date, number passing all core conditions, number whose close is above the prior 20-session high, commit hash if pushed, whether the public page was verified, and link https://hoihoichristy.github.io/futu-breakout-dashboard/. State that the universe is fixed and not a daily full-market rescreen.

On an incomplete/error response, inconsistent dates, missing authentication, or failed build, leave the live `index.html` untouched and report the precise blocker. If the push succeeds but Pages does not show the new date within 120 seconds, report “push succeeded; Pages still rebuilding” rather than claiming live verification. Do not make an investment recommendation.
