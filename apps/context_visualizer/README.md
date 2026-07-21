# Context Visualizer

Canonical live Market Context + Paper Trade visual stack.

## Layout

- `public/` — static viewer (ops-styled, dark/light/system themes)
- `public/data/` — generated visual JSON (gitignored except `.gitkeep`)
- `generate_lifecycle_context_data.py` — lifecycle/context visual data builder

## Run

```bash
make context-visual-stack-start
make context-visual-stack-status
```

URL: http://127.0.0.1:8765/

Visual-only: no paper ledger writes, no decision-log writes, no controller control, execution disabled.
