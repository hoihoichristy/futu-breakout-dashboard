# Futu Breakout Dashboard

Self-contained Futu U.S. ordinary-share/ADR technical dashboard.

- **Dynamic candidate universe:** each daily update starts from a paginated Futu U.S. screen; the old 53-symbol `universe.csv` remains an archival baseline and is not the daily scan universe. Market-data K-lines are fetched only for candidates that meet the documented prefilter.
- **Screen prefilter:** U.S.-listed securities, market cap >$5 billion, price >$5, Futu 60-session return ≥18% as a recall buffer, 50-session average dollar turnover >$5 million, and 20-session average amplitude ≥3% as a loose volatility proxy. Exact 63-session return ≥20% and ADR20 >3.5% are recalculated from fresh K-lines; detailed consolidation, SMA200, prior-low, and EMA conditions are also checked.
- **Security type:** Futu instrument type and Futu security-name descriptors are used to retain ordinary shares/ADRs while excluding ETFs and identifiable preferred/CDI/fund/derivative classes. Unverified labels are excluded and reported.
- **Source:** Futu market screener, security reference data, and forward-adjusted regular-session daily K-lines retrieved through the Manus Futu connector. No substitution with Yahoo or another market-data source.
- **Schedule:** 06:00 Asia/Hong_Kong Tuesday–Saturday, after the previous U.S. session. Manus refreshes `index.html`; GitHub Pages deploys `main:/`.
- **Page:** https://hoihoichristy.github.io/futu-breakout-dashboard/
- **Current-page timing:** the existing page remains its last successfully published snapshot until a new dynamic-screen run completes and its exact HTML hash is verified.
- **Short history:** unavailable indicators remain null/unverified using their original lookbacks; they are never replaced by shorter estimates and cannot count as a complete core pass.
- **Freshness:** active symbols must agree on their latest daily date. Missing symbols, invalid OHLC, failed source calls, ordinary date mismatches, and uncertain security classes abort the publication.
- **QMMM-only suspension exception:** the user authorized retaining QMMM historical candles/date only when a fresh Futu quote confirms `SUSPENDED`. Its current metrics remain unverified and are excluded from current rankings and pass/breakout counts.
- **Deployment verification:** the publisher checks the exact live HTML SHA-256. Private run logs and raw source results are Git-ignored and never published.

The HTML embeds Plotly, the rows selected in that run and their dated candles for browser/offline use. ADR20 is average daily intraday range, not Wilder ATR. A close above the prior 20-session high is only a price-level event, not confirmed breakout or investment advice.

See [`DAILY_UPDATE.md`](DAILY_UPDATE.md) for the full daily workflow.
