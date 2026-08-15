# S4.1 Independent TF Paper — LIVE1B Replacement Design

Status: **REPLACEMENT DESIGN** (not A/B, not shadow-vs-LIVE1B)  
Mode: paper only · `execution_enabled=false`  
Date: 2026-08-15

## 1. Goal

Replace LIVE1B paper routing with the **S4.1 independent timeframe contract**:

```text
context/state @ each TF's own bar close
  → Manager emits OPEN_*/HOLD/CLOSE/NO_ACTION per TF
  → TimeframeTrader(M15|M30|H1|H4) executes only its book
```

LIVE1B’s event→fill path is **out of contract**. We do not compare to it for acceptance.
Acceptance = independent TF traders behave correctly under S4.1 kinematics, without lag/dual-writers/stuck books.

Reference density (why we want this back): S4.1 Jul 27 alone produced **14 OPEN** intents; closed trades across M15/M30/H1 reached **25** in the short live window before the stack was stopped.

---

## 2. What “independent TF” means here

| Rule | Meaning |
|------|---------|
| Own clock | Each TF evaluates at its own confirmed `source_bar_close` |
| Own command | Manager emits one command row per TF per evaluation |
| Own agent | Separate `TimeframeTrader` process + book; never closes another TF |
| Own risk sleeve | Portfolio risk coordinator caps per TF / gross; no netting across TF |
| Shared cognition OK | One lifecycle memory sampled at different clocks (S4.1 adapter) — **not** four LIVE1B provisional engines |

Not independent: one `IntrabarPaperEngine` consuming a mixed journal and entering all TFs in-process (LIVE1B).

---

## 3. Cutover shape (replace, do not dual-run paper)

```text
BEFORE
  cognition (ok to keep) → journal → LIVE1B paper manager → epoch books
  S4.1 manager/traders = DEAD, books stuck OPEN LONG from Jul 27–28

AFTER
  cognition / lifecycle / MTF availability / M15 decision log (catch-up) = context plane
  timeframe_manager_daemon → command bus → trader_M15..H4 → FRESH books
  LIVE1B paper manager = STOPPED (no paper consumer of journal)
```

Journal may still be written for visuals/audit. It must **not** open paper positions after cutover.

---

## 4. Hard blockers (must clear before start)

Measured 2026-08-15:

| Blocker | State | Required action |
|---------|-------|-----------------|
| LIVE1B paper manager running | pid alive | Stop before S4.1 traders write any paper |
| S4.1 manager/traders | all `alive=false` | Start via `timeframe_trading_ctl.sh` after fresh books |
| Production books stuck OPEN | M15/M30/H1/H4 LONG since Jul 27–28 | **Archive + reset** — do not resume those positions |
| Command memory tip | frozen 2026-08-03 | New activation boundary; resume append from new boundary |
| M15 confirmation catch-up (Aug) | 0 remaining | OK for M15 decision lineage |
| MTF availability tip | fresh (~minutes) | OK |

Dual paper writers (LIVE1B + S4.1) are **forbidden**.

---

## 5. Fresh-epoch procedure (replacement)

1. **Preflight** — `scripts/research/s41_replacement_preflight.py` must exit 0 (or report only WAIVE-able items).  
2. **Stop LIVE1B paper** — stop `run_intrabar_paper_manager` (and any supervisor that respawns it). Keep cognition if desired.  
3. **Archive stuck S4.1 books + manager artifacts** to `data/archive/s41_pre_replacement_<stamp>/`.  
4. **Install empty books** for M15/M30/H1/H4 + empty/new command memory (or truncated after activation boundary).  
5. **Set activation boundary** = cutover UTC (commands before boundary ignored).  
6. **Start** `timeframe_manager` then `trader_M15..H4` via ctl (paper-only flags).  
7. **Verify 15–30 min**: each TF gets its own commands; OPEN only on actionable directional state; no cross-TF book writes; no LIVE1B fills accruing.  
8. **OPS/truth source** — point paper truth to S4.1 books (not LIVE1B epoch).

Exact archive/reset automation is a follow-on script; do not “just start” on Jul-28 opens.

---

## 6. Lag / bug acceptance gates (post-start)

Must hold for the first live session:

1. **Command cadence** — manager appends when MTF evaluation advances; no multi-hour silence while availability tip moves.  
2. **Independence** — a CLOSE/OPEN on M15 never mutates M30 book.  
3. **Intent clarity** — every paper fill traces to `command_id` with intent `OPEN_*`/`CLOSE` (never to raw `CONTEXT_*`).  
4. **Occupancy** — at most one open position per TF; no pile of `status=OPEN` without close.  
5. **Stale context** — M15 decisions not lagging confirmed opposite ACTIVE (catch-up already in logger).  
6. **No LIVE1B paper** — `run_intrabar_paper_manager` not running; epoch books mtime frozen after cutover.

Fail any gate → stop traders, keep archive, do not declare replacement successful.

---

## 7. Out of scope

- Shadow A/B scoring vs LIVE1B trade list  
- Promoting provisional journal FLIPs into OPEN  
- Real execution / exchange  
- Keeping LIVE1B paper “for a while” alongside S4.1

---

## 8. Artifacts

| Item | Path |
|------|------|
| This design | `docs/design/S41_COMMAND_RELAY_PROTOTYPE.md` (replacement semantics) |
| Contract constants | `src/btc_ml/trading/s41_command_relay/contract.py` |
| Preflight | `scripts/research/s41_replacement_preflight.py` |
| Dry intent check | `scripts/research/s41_kinematics_prototype_dry_run.py` |
| Process ctl | `scripts/timeframe_trading_ctl.sh` |

---

## 9. Decision

**Paper control plane = S4.1 independent TF manager/traders.**  
LIVE1B is retired as the entry router. Context plane stays; command→trader plane is restored on a **fresh** book epoch after LIVE1B is stopped.
