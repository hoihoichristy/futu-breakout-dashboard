#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <built-dashboard.html> <as-of-YYYY-MM-DD> [repo-dir]" >&2
  exit 2
fi
HTML=$(realpath "$1")
AS_OF=$2
REPO_DIR=${3:-/home/ubuntu/futu-breakout-dashboard-deploy}
REPO_URL=${FUTU_REPO_URL:-"https://github.com/hoihoichristy/futu-breakout-dashboard"}
PAGES_URL=${FUTU_PAGES_URL:-"https://hoihoichristy.github.io/futu-breakout-dashboard/"}
BRANCH=${FUTU_BRANCH:-main}
if [[ -n "${FUTU_LOG_PATH:-}" ]]; then
  mkdir -p "$(dirname "$FUTU_LOG_PATH")"
  exec > >(tee -a "$FUTU_LOG_PATH") 2>&1
fi

[[ -s "$HTML" ]] || { echo "Refusing to publish an empty/missing HTML file: $HTML" >&2; exit 1; }
grep -Fq "$AS_OF" "$HTML" || { echo "Dashboard does not contain expected data date $AS_OF" >&2; exit 1; }
git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null
normalize_repo() {
  local value="$1"
  value="${value%.git}"
  value="${value#https://github.com/}"
  value="${value#http://github.com/}"
  value="${value#git@github.com:}"
  value="${value#ssh://git@github.com/}"
  printf '%s' "$value"
}
ORIGIN=$(git -C "$REPO_DIR" remote get-url origin)
[[ "$(normalize_repo "$ORIGIN")" == "$(normalize_repo "$REPO_URL")" ]] || {
  echo "Origin '$ORIGIN' does not match configured repository '$REPO_URL'" >&2; exit 1;
}
GH_PAGER=cat gh auth status >/dev/null 2>&1 || {
  echo "GitHub authentication is unavailable in this scheduled run; nothing was pushed." >&2; exit 1;
}

# Pull first so a remote README/settings edit is not overwritten.
git -C "$REPO_DIR" pull --ff-only origin "$BRANCH"
install -m 0644 "$HTML" "$REPO_DIR/index.html"
git -C "$REPO_DIR" add -- index.html
if git -C "$REPO_DIR" diff --cached --quiet; then
  echo "No change: the published dashboard already matches the latest Futu data ($AS_OF)."
  exit 0
fi

if ! git -C "$REPO_DIR" config user.name >/dev/null; then
  git -C "$REPO_DIR" config user.name "Futu dashboard updater"
fi
if ! git -C "$REPO_DIR" config user.email >/dev/null; then
  git -C "$REPO_DIR" config user.email "noreply@users.noreply.github.com"
fi
git -C "$REPO_DIR" commit -m "Refresh Futu dashboard data ${AS_OF}"
git -C "$REPO_DIR" push origin "$BRANCH"
COMMIT=$(git -C "$REPO_DIR" rev-parse --short HEAD)
echo "Pushed commit $COMMIT; GitHub Pages should rebuild from $BRANCH:/ ."

# Pages deployment is asynchronous. Verify the public page gets the new date;
# don't roll back a successful push if the CDN/build is still propagating.
for attempt in $(seq 1 12); do
  tmp=$(mktemp)
  if curl -fsSL --max-time 20 -H 'Cache-Control: no-cache' \
      "${PAGES_URL}?refresh=$(date +%s%N)" -o "$tmp" 2>/dev/null && grep -Fq "$AS_OF" "$tmp"; then
    rm -f "$tmp"
    echo "Verified live Pages content for $AS_OF: $PAGES_URL"
    exit 0
  fi
  rm -f "$tmp"
  sleep 10
done
echo "Push succeeded, but the live page did not show $AS_OF within 120 seconds; Pages may still be rebuilding: $PAGES_URL" >&2
exit 3
