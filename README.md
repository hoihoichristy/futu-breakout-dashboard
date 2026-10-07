# Futu Breakout Dashboard

Self-contained interactive snapshot of the Futu U.S. common-stock/ADR screen.

- **Universe:** the 53 symbols in `universe.csv` (fixed list; daily refresh does not discover new candidates).
- **Market data:** Futu daily K-lines, fetched by the connected Manus Futu connector.
- **Schedule:** Manus runs after the prior U.S. close at 06:00 Asia/Hong_Kong Tuesday–Saturday; a successful `index.html` push to `main` triggers GitHub Pages publication.
- **Page:** https://hoihoichristy.github.io/futu-breakout-dashboard/
- **Freshness:** the dashboard displays the latest common Futu trading date. The update aborts instead of replacing the page when any ticker is missing, the series is insufficient, or data dates disagree.
- **No data-source substitution:** the GitHub-hosted runner cannot directly call the Manus-only Futu MCP connector; Futu retrieval is performed by Manus, while GitHub Pages serves the refreshed static HTML.

The embedded page is self-contained (including Plotly.js, the metrics and daily candles). A close above the prior 20-session high is only a price-level event, not confirmed breakout advice.
