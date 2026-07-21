# Market Context Viewer — Clean Visual Mode

## Root cause of visual degradation

The Stage-15 uncertainty overlay painted **too many chart decorations** on top of
the original Clean View:

1. Vertical dashed **AUCTION_NEUTRALIZATION / INVALIDATED** markers with rotated labels
2. **Text labels** drawn inside candidate/challenged regions (`CANDIDATE LONG`, etc.)
3. A bulky multi-field **pinned inspector card** over the price area
4. An expanded legend advertising candidate subtypes and neutralization

Those annotations made the chart unreadable while confirmed green/red regions were
already enough — doubt only needed the same directional **hatch**, not event spam.

## Clean mode (default)

| Visual | Mapping | Render |
|---|---|---|
| Confirmed LONG | episode `context == LONG_CONTEXT` and not challenged-dominant | green **solid** fill |
| Confirmed SHORT | episode `context == SHORT_CONTEXT` and not challenged-dominant | red **solid** fill |
| Uncertain / doubt LONG | uncertainty segment `CANDIDATE` or `CHALLENGED` with `direction == LONG_CONTEXT` (also episode hatch when challenged-dominant) | green **hatch** only |
| Uncertain / doubt SHORT | same with `direction == SHORT_CONTEXT` | red **hatch** only |
| OBSERVE / NO_ACTIVE_CONTEXT | everything else | **no fill** |

Data still comes from:

- `lifecycle_context_episodes.json` — confirmed / episode challenged bands
- `lifecycle_uncertainty_segments.json` — candidate / developing / challenged regions

Markers (`INVALIDATED`, `AUCTION_NEUTRALIZATION`) may still exist in the JSON for
debug/tooling, but **clean mode never draws them**.

## Removed from clean view

- `drawUncertaintyMarkers` (vertical lines + AUCTION NEUTRALIZATION labels)
- Region text labels painted on the canvas
- Click-to-pin multi-field inspector overlay
- Legend entries: Candidate Long/Short, Auction Neutralization
- Inspector CSS / pinned-card styles

## Kept

- Solid green/red episode bands (original clean language)
- Hatched green/red uncertainty regions (candidate / challenged / developing)
- Compact one-line hover readout (`time · close · active · lifecycle`)
- Compact 4-item legend
- Top status / auto-refresh line
- Debug link (`./debug.html`) remains separate from clean default

## Out of scope

Model, auction, cognitive, lifecycle, execution, feed/runtime, and dashboard health
logic are unchanged. This is viewer rendering only.
