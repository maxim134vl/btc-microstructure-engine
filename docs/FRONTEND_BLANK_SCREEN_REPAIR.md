# Frontend Blank Screen Repair (Stage 14)

## Problem

Runtime stack was healthy (API `:8080`, UI `:5173`, context viewer `:8765`, refresher alive,
`visual_data_stale=false`) but the browser showed a blank white page for the dashboard.

## Root cause

Vite ESM import failure:

```
SyntaxError: The requested module '/src/components/status/index.ts'
does not provide an export named 'translateHealthDimensionStatus'
```

Stage 13 added `translateRuntimeStability` / `translateHealthDimensionStatus` in
`status/translate.ts`, and `OpsDashboard.tsx` imported them from `status/index.ts`,
but `index.ts` did not re-export those names. The module graph failed before React
mounted, leaving `#root` empty.

Secondary issues:

1. Context viewer linked `./styles.css` which 404'd (shell still present via `lifecycle.css`).
2. Viewer lacked global error / unhandledrejection display if JS/data failed.
3. Refresher `log_line()` printed and appended to the same file while `runtime_stack`
   already redirected stdout into that log → duplicated lines.

## Fixes

- Re-export Stage 13 translators from `status/index.ts`.
- Null-safe status mappers / translators for missing optional fields.
- `SectionErrorBoundary` around OpsDashboard sections so one section throw cannot
  blank the whole page.
- Viewer: visible shell + error panel, `error` / `unhandledrejection` handlers,
  `Array.isArray` fallbacks, cache-bust + `cache: "no-store"` retained.
- Stub `styles.css` to stop 404.
- Refresher: avoid double-writing the log when stdout is redirected (non-TTY);
  stable `get_refresher_logger()` handlers.

## Out of scope (unchanged)

- Model / retrain
- Pipeline / execution
- Market context lifecycle arbitration rules
- Collector / feed
- Benchmark producer
- Stage 12 refresher interval / builder behavior (logging only)
- Stage 13 health semantics

## Verification

```bash
venv/bin/python -m pytest tests/test_frontend_blank_screen_regression.py \
  tests/test_market_context_visual_refresher.py \
  tests/test_ops_health_semantics.py -q

make runtime-stack-stop && make runtime-stack
# Browser: http://127.0.0.1:5173/# and http://127.0.0.1:8765/
```
