# GITLINK DECISION — `btc-auction-runtime`

## Verdict

**B. Stale unused gitlink** — removed from this branch.

## Evidence

| Check | Result |
|-------|--------|
| `git ls-files -s btc-auction-runtime` (before) | `160000 1c002e2f…` (gitlink mode) |
| `.gitmodules` | **absent** |
| Working tree content | empty directory only |
| Submodule object `1c002e2f…` locally | **missing** (`git cat-file` fails) |
| Production refs (`src/`, `scripts/live/`, `dashboard/`) | **none** |
| Only remaining mention | `pytest.ini` `norecursedirs` (exclusion, not a dependency) |
| Prior intent | commit `e497f11` on `gitea/release` already deleted this gitlink with message *"Also removed the empty btc-auction-runtime gitlink"* — that commit is **not** an ancestor of `memory/canonical-system` / this pack tip |

## Action taken

1. `git rm` the gitlink path.
2. Drop `btc-auction-runtime` from `pytest.ini` `norecursedirs`.
3. Verify `git submodule status` no longer fatals with missing mapping.

## Not done

- Did **not** invent a `.gitmodules` mapping.
- Did **not** vendor replacement code.
- Did **not** fetch the unreachable submodule object.

## Validation

```bash
git submodule status   # must exit 0 without "no submodule mapping" fatal
```
