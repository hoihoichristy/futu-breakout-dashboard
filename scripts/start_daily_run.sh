#!/usr/bin/env bash
set -euo pipefail

if [[ $# -gt 2 ]]; then
  echo "Usage: $0 [repo-dir] [run-tag]" >&2
  exit 2
fi
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=${1:-$(cd "$SCRIPT_DIR/.." && pwd)}
RUN_TAG=${2:-$(date -u +%Y%m%dT%H%M%SZ)}
[[ -d "$REPO_DIR/.git" ]] || { echo "Not a Git repository: $REPO_DIR" >&2; exit 1; }
[[ "$RUN_TAG" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Unsafe run tag: $RUN_TAG" >&2; exit 2; }

STARTED_EPOCH=$(date +%s)
RAW_DIR="${TMPDIR:-/tmp}/futu-refresh-${RUN_TAG}"
RUN_DIR="$REPO_DIR/.runlogs/$RUN_TAG"
LOG_PATH="$RUN_DIR/run.log"
METRICS_PATH="$RUN_DIR/metrics.csv"
REPORT_PATH="$RUN_DIR/report.md"
INDEX_PATH="$RAW_DIR/index.html"
STATE_PATH="${TMPDIR:-/tmp}/futu-refresh-${RUN_TAG}.state"

mkdir -p "$RAW_DIR" "$RUN_DIR"
{
  printf 'STARTED_EPOCH=%q\n' "$STARTED_EPOCH"
  printf 'RAW_DIR=%q\nRUN_DIR=%q\nLOG_PATH=%q\n' "$RAW_DIR" "$RUN_DIR" "$LOG_PATH"
  printf 'METRICS_PATH=%q\nREPORT_PATH=%q\nINDEX_PATH=%q\nSTATE_PATH=%q\n' "$METRICS_PATH" "$REPORT_PATH" "$INDEX_PATH" "$STATE_PATH"
} > "$STATE_PATH"
ln -sfn "$STATE_PATH" "${TMPDIR:-/tmp}/futu-refresh-current.state"
{
  printf 'START utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'run_tag=%s\nrepo_dir=%s\nraw_dir=%s\nrun_dir=%s\n' "$RUN_TAG" "$REPO_DIR" "$RAW_DIR" "$RUN_DIR"
  printf 'futu_source=Manus Futu MCP\ngithub_repo=%s\n' "$(git -C "$REPO_DIR" remote get-url origin)"
} > "$LOG_PATH"

# Output lines: start_epoch, raw_dir, run_dir, log_path, metrics_path,
# report_path, built_index_path, state_file. These are data paths, not secrets.
printf '%s\n' "$STARTED_EPOCH" "$RAW_DIR" "$RUN_DIR" "$LOG_PATH" "$METRICS_PATH" "$REPORT_PATH" "$INDEX_PATH" "$STATE_PATH"
