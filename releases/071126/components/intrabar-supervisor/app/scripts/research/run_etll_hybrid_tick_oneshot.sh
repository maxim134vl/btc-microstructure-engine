#!/bin/bash
# One-shot Hybrid tick FULL-SPAN run + Tiger archive sync + performance report + RU analytics PDF.
# Causal lifecycle alignment is passed explicitly so the run is self-documenting.
# NO launchd / keepalive. NO rolling windows: single full-span Hybrid replay.
set -uo pipefail
cd /Users/fontecrypto/btc-ml
LOG=/tmp/etll_hybrid_tick_oneshot.log
PIDFILE=/tmp/etll_hybrid_tick_oneshot.pid
REPORT_MARKER=/tmp/etll_hybrid_tick_oneshot_report.done
TIGER_ARCHIVE=/Volumes/MaksTiger/btc-ml/research/etll_hybrid_tick/archive
SANDBOX=data/research/external_traders/etll_hybrid_tick

if pgrep -f 'run_etll_hybrid_tick_lived_replay.py' >/dev/null 2>&1; then
  echo "REFUSE: hybrid tick already running" >&2
  exit 1
fi

rm -f "$REPORT_MARKER"
echo $$ > "$PIDFILE"
echo "===== ONESHOT START $(date -u +%Y-%m-%dT%H:%M:%SZ) =====" | tee "$LOG"

PYTHONUNBUFFERED=1 python3 -u scripts/research/run_etll_hybrid_tick_lived_replay.py \
  --flush-every 200 \
  --lifecycle-align bar_close \
  --protective-scan vectorized \
  --durable-archive "$TIGER_ARCHIVE" \
  >>"$LOG" 2>&1
HYBRID_EXIT=$?
echo "===== HYBRID EXIT:$HYBRID_EXIT $(date -u +%Y-%m-%dT%H:%M:%SZ) =====" | tee -a "$LOG"

# Belt-and-suspenders: sync whatever books exist to Tiger even if in-process archive failed.
PYTHONUNBUFFERED=1 python3 -u scripts/research/sync_etll_hybrid_tick_archive_to_tiger.py --once \
  --durable-root "$TIGER_ARCHIVE" \
  >>"$LOG" 2>&1 || true

if [[ "$HYBRID_EXIT" -ne 0 ]]; then
  echo "hybrid failed; skip report" | tee -a "$LOG"
  exit "$HYBRID_EXIT"
fi

# Resolve the epoch this run actually produced; reports must never guess it.
EPOCH=$(python3 -c "
import json,sys
try:
    print(json.load(open('$SANDBOX/summary.json'))['paper_epoch_id'])
except Exception as exc:
    print('', end=''); sys.stderr.write(str(exc))
")
if [[ -z "$EPOCH" ]]; then
  echo "cannot resolve paper_epoch_id; skip reports" | tee -a "$LOG"
  exit 3
fi
echo "===== EPOCH:$EPOCH =====" | tee -a "$LOG"

TRADES="$TIGER_ARCHIVE/$EPOCH/books/trades.jsonl"
if [[ ! -s "$TRADES" ]]; then
  TRADES="$SANDBOX/data/trading/intrabar_paper/$EPOCH/books/trades.jsonl"
fi
echo "===== TRADES:$TRADES =====" | tee -a "$LOG"

PYTHONUNBUFFERED=1 python3 -u scripts/research/report_etll_hybrid_tick_performance.py \
  --trades "$TRADES" \
  --paper-epoch-id "$EPOCH" \
  >>"$LOG" 2>&1
REPORT_EXIT=$?
echo "===== REPORT EXIT:$REPORT_EXIT $(date -u +%Y-%m-%dT%H:%M:%SZ) =====" | tee -a "$LOG"

PYTHONUNBUFFERED=1 python3 -u scripts/research/build_etll_hybrid_tick_analytics_pdf_ru.py \
  --trades "$TRADES" \
  --epoch "$EPOCH" \
  --out-name HYBRID_TICK_FULL_ANALYTICS_RU_FINAL.pdf \
  >>"$LOG" 2>&1
PDF_EXIT=$?
echo "===== PDF EXIT:$PDF_EXIT $(date -u +%Y-%m-%dT%H:%M:%SZ) =====" | tee -a "$LOG"

date -u +%Y-%m-%dT%H:%M:%SZ > "$REPORT_MARKER"
exit $(( REPORT_EXIT | PDF_EXIT ))
