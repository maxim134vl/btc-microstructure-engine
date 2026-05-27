# ONTOLOGY OVERLAP MATRIX

**Status:** Phase 3B  
**Module:** `ontology_overlap_matrix.py`

---

## Tracked Pairs

| Pair | Purpose |
|------|---------|
| `BUYING_CLIMAX` vs `HIGH_AVERAGE_VOLUME` | Upside semantic compression |
| `HIGH_AVERAGE_VOLUME` vs `BALANCED_AUCTION` | Neutral bucket bleed |
| `STOPPING_VOLUME` vs `ABSORPTION_RECOVERY` | Absorption semantic overlap |
| `TREND_EXHAUSTION` vs `BUYING_CLIMAX` | Exhaustion vs climax overlap |

## Exports

| Field | Meaning |
|-------|---------|
| `ontology_overlap_matrix` | JSON pair-wise overlap scores |
| `semantic_overlap_score` | Aggregate overlap index |
| `ontology_ambiguity_heatmap` | JSON per-label ambiguity intensity |

## Goal

Identify remaining ontology compression zones without rewriting ontology.
