# VPS Full-Model Deployment Pack

Docker Compose pack that runs the **full host hybrid model** (no exclusions):
everything started by `scripts/btc_ml_host.py` `model_start()` + `MODEL_CTLS` +
dashboard — including EQCORR, Auction, Structural STP, BE33, TimeframeManager
(4 TF + Anti-Saw), assurance suite, `run.py`, collector watchdog, and context
refresh daemon.

Design: [docs/deploy/VPS_DOCKER_ASSEMBLY_DESIGN.md](../../docs/deploy/VPS_DOCKER_ASSEMBLY_DESIGN.md)

## Non-negotiable

- **Full model by default** — no compose profiles that exclude EQCORR or any
  required unit from §8 of the design doc.
- Paper-only / real execution disabled (config + entrypoint guard).
- No exchange trading credentials required.
- No bind-mount of host live Mac `data/`.
- Telegram is **Plane C** (sibling compose), not in this compose file.

## Quick start

```bash
cp deploy/vps/.env.example deploy/vps/.env   # never commit secrets

./scripts/deploy/vps_stack.sh doctor
./scripts/deploy/vps_stack.sh bootstrap
./scripts/deploy/vps_stack.sh build
./scripts/deploy/vps_stack.sh up
./scripts/deploy/vps_stack.sh health
./scripts/deploy/vps_stack.sh logs

# Telegram sibling (Plane C)
./scripts/deploy/vps_telegram.sh doctor
./scripts/deploy/vps_telegram.sh up

./scripts/deploy/vps_stack.sh down
```

## Ports (defaults)

| Surface | Host port |
|---------|-----------|
| OPS API | `18080` |
| Dashboard UI | `15173` |
| Trade chart | `18765` |

## Volumes

- Model data: `btc_ml_data_vps` → `/app/data`
- Visual public JSON: `btc_ml_visual_public_vps`
- Smoke: `btcml-vps-smoke` / `btc_ml_data_vps_smoke`

## Images

- `btc-ml-vps-runtime`
- `btc-ml-vps-ops-api`
- `btc-ml-vps-dashboard-ui`

## Service graph

See [SERVICE_GRAPH.md](./SERVICE_GRAPH.md).

## Bootstrap

`scripts/deploy/bootstrap_vps_environment.py` creates a new `VPS_DEPLOY` paper
epoch via `create_epoch` / `activate_epoch` / `build_trading_contract_manifest`.
It refuses Mac live paths and never copies the live epoch.

## Related notes

- [FRONTEND_DEPENDENCY_NOTE.md](./FRONTEND_DEPENDENCY_NOTE.md)
- [GITLINK_DECISION.md](./GITLINK_DECISION.md)
- [CTO_DEPLOYMENT_VALIDATION.md](./CTO_DEPLOYMENT_VALIDATION.md) (historical CTO smoke notes)
