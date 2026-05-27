# HAV SEMANTIC ANALYSIS

**Status:** Phase 3B — bucket integrity audit  
**Module:** `hav_semantic_analysis.py`

---

## Question

Is `HIGH_AVERAGE_VOLUME`:
- **A.** Valid neutral high-effort zone, or
- **B.** Unresolved ontology compression / ambiguity bucket?

## Exports

| Field | Meaning |
|-------|---------|
| `hav_semantic_density` | Share of climax events classified as HAV |
| `hav_behavioral_dispersion` | Feature dispersion within HAV events |
| `hav_ontology_ambiguity_score` | Ambiguity / overflow proxy |
| `hav_contradiction_concentration` | Contradiction concentration |
| `hav_entropy_neutrality` | Proximity to neutral efficiency decay |

## Replay

```bash
venv/bin/python3 scripts/replay_validation/ontology/hav_behavior_analysis.py
```
