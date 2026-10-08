# Futu Breakout Dashboard

Self-contained Futu U.S. common-stock/ADR technical dashboard.

- **Fixed universe:** all 53 reviewed symbols in `universe.csv`; daily refresh never adds/removes symbols or scans the full market.
- **Source:** Futu forward-adjusted regular-session daily K-lines, retrieved through the Manus Futu connector. No substitution with Yahoo or another source.
- **Schedule:** 06:00 Asia/Hong_Kong Tuesday–Saturday, after the previous U.S. session. Manus updates `index.html`; GitHub Pages deploys `main:/`.
- **Page:** https://hoihoichristy.github.io/futu-breakout-dashboard/
- **Short history:** at least one valid daily bar is retained. Each indicator keeps its original lookback; unavailable values are null/unverified, not zero or shortened estimates, and cannot count as a complete core pass.
- **Normal-trading freshness:** all normal-trading symbols must agree on their latest daily date. Missing symbols, invalid OHLC, failed source calls, other date mismatches and class failures abort the update.
- **QMMM-only suspension exception:** the user authorized retaining QMMM's historical candles and last-trade date while a fresh Futu quote confirms `SUSPENDED`. Its current metrics remain unverified and are excluded from core/breakout counts and rankings. The normal common analysis date is not QMMM's historical date. If trading resumes, normal date validation applies again.
- **Deployment verification:** the publisher checks the exact live HTML SHA-256, not merely a date string. Private run logs and raw source results are Git-ignored and never published.

The HTML embeds Plotly, all reviewed rows and dated candles for browser/offline use. ADR20 is average daily intraday range, not Wilder ATR. A close above the prior 20-session high is only a price-level event, not confirmed breakout or investment advice.

See `DAILY_UPDATE.md` for the reproducible daily process.
