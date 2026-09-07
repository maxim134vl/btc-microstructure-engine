# VPS Docker Assembly Design — Full Model + Dashboard + Telegram

**Status:** D0/D1 **in progress → done** (packaging under `deploy/vps/`; D2+ not cut over)  
**Date:** 2026-08-26  
**Decision:** **resume & converge** prior work — not greenfield, not archive VPS revive  
**Pointer:** full-model Compose + entrypoints live at [`deploy/vps/`](../../deploy/vps/) — operator entry `./scripts/deploy/vps_stack.sh`  

### Non-negotiable (operator rule)

> **В Docker должна быть вся модель целиком, без исключений.**  
> 4 timeframe (M15/M30/H1/H4) + Anti-Saw (внутри TimeframeManager) + все Shadow  
> (Structural Stop/Take, STP_BE33, Auction, EQCORR) + LIVE1A/B + supervisor + assurance  
> + dashboard + Telegram.  
> Никаких compose-profile «потом включим EQCORR». Нет MVP с урезанным process set.

Source of truth: `scripts/btc_ml_host.py` — `model_start()` + `MODEL_CTLS` + dashboard profile.

---

## 0. Verdict (коротко)

| Вопрос | Ответ |
|--------|--------|
| Была ли сборка? | **Да.** Root `compose.yaml` (local cold-start), CTO pack (smoke PASS), Telegram sibling |
| Почему остановилась? | Host hybrid ушёл вперёд; Docker не догнали; `deploy/` не влит в main |
| Что крутится сейчас? | Host-era `./scripts/btc_ml` — не Docker |
| Новый докер с нуля? | **Нет.** CTO pack = packaging skeleton; process set = **полный host hybrid** |
| EQCORR / Auction / assurance | **Включены по умолчанию** вместе со всей моделью |
| Anti-Saw | Не отдельный сервис: rails в `timeframe_manager` (уже в модели) |

---

## 1. Inventory — что уже есть

### 1.1 Main repo `/Users/fontecrypto/btc-ml`

| Артефакт | Состояние |
|----------|-----------|
| `compose.yaml` | Local cold-start: `model-runtime`, `dashboard-api`, `dashboard-ui`, `context-refresher`, `trade-chart` |
| `docker/Dockerfile.runtime` + `scripts/docker/model_runtime.py` | PID-1 multiplex; paper-only; LIVE1B + STP BE33 recovery — **неполный** vs host |
| `scripts/btc-ml-stack` | Refuse если host writers alive |
| `run/docker_model_runtime_status.json` | READY **2026-08-09** — Docker сейчас **не запущен** |
| `deploy/vps/` | **D0/D1 landed** — full-model compose (EQCORR always on), entrypoints, `vps_stack.sh` |

**Дыры root compose vs полный hybrid:** нет TF manager, нет полного shadow/assurance set, bind `.:/app`, naming drift.

### 1.2 Sibling CTO pack

Smoke **PASS**, named volume, paper-only contract. **Тонкий** graph (нет TF manager, BE33, auction, assurance, chart). Использовать как **упаковку**, не как урезанный process set.

### 1.3 Sibling Telegram

Отдельный compose (`bot` + `publisher` + `redis`). Publisher **ro** на runtime. Не вшивать в model compose, но **обязан** быть в VPS-сборке рядом.

### 1.4 Archive microstructure VPS

Другой продукт. **Не использовать.**

---

## 2. Target architecture (VPS)

Один операторский выход: **stack up / down / health**.  
Внутри — три plane’а. Plane A = **полная модель**.

```
                    ┌─────────────────────────────────────┐
                    │           VPS host (Linux)          │
                    │  docker compose (project: btcml)    │
                    └─────────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          ▼                           ▼                           ▼
┌──────────────────┐    ┌──────────────────────┐    ┌─────────────────────┐
│  PLANE A         │    │  PLANE B             │    │  PLANE C            │
│  FULL MODEL      │    │  OPS SURFACE         │    │  TELEGRAM OPS       │
│  (paper-only)    │    │  (read-mostly)       │    │  (sibling compose)  │
└────────┬─────────┘    └──────────┬───────────┘    └──────────┬──────────┘
         │ writes                  │ reads                      │ reads
         ▼                         ▼                            ▼
   volume: btc_ml_data ◀───────────┴────────────────────────────┘
```

### Plane A — Full Model Runtime (write plane)

**Правило:** Docker `model up` ≡ host `./scripts/btc_ml model start` по составу процессов.  
Разница только в упаковке (containers + volumes), не в том, что включено.

#### A1. Core runtime (как `model_start()` до MODEL_CTLS)

| Unit | Host launcher | Notes |
|------|---------------|--------|
| `collector-watchdog` | `collector_watchdog.py --required-only` | required |
| `canonical-runtime` | `run.py` | required |
| `context-refresh-daemon` | `scripts/ops/context_refresh_daemon_ctl.sh` | required |
| `timeframe-manager` | `timeframe_manager_daemon` / ctl | **4 TF + Anti-Saw rails** |
| S4.1 traders | — | **STOPPED** (как на host: `run_tf_ctl stop traders`) |

Anti-Saw **не** отдельный контейнер: `ANTI_SAW_*` в `TimeframeManager` на M15/M30/H1/H4.

#### A2. MODEL_CTLS — всё, без профилей-исключений

| Unit | Host ctl / runner | Role |
|------|-------------------|------|
| `live1a` / cognition | `intrabar_cognition_ctl` | market + journal |
| `live1b` / paper | `intrabar_paper_ctl` | paper books |
| `intrabar-supervisor` | `intrabar_process_supervisor_ctl` | process assurance |
| `stp-be33` | `shadow_stp_be33_ctl` | управление позицией (shadow) |
| `trd-outcome2` | `trd_outcome2_ctl` | outcome refresh (host: optional alive) |
| `shadow-auction` | `shadow_auction_ctl` | Auction shadow |
| `shadow-structural` | `shadow_structural_protection_ctl` | Structural Stop/Take |
| `shadow-eqcorr` | `shadow_economic_correlation_ctl` | **EQCORR — всегда в стеке** |
| `shadow-model` | `shadow_model_ctl` | assurance |
| `behavioral-validation` | `behavioral_validation_ctl` | assurance |
| `economic-validation` | `economic_validation_ctl` | assurance |
| `external-data-toxicity` | `external_data_toxicity_ctl` | assurance |
| `current-toxicity` | `current_toxicity_ctl` | assurance |
| `incident-correlation` | `incident_correlation_ctl` | assurance |
| `promotion-gate` | `promotion_gate_ctl` | assurance |
| `model-assurance-summary` | `model_assurance_summary_ctl` | assurance |

#### Packaging choice (implementation)

Два допустимых варианта (оба = полный set):

1. **Multi-service compose** — 1:1 сервис на unit выше (проще health/restart, ближе CTO).  
2. **`model-runtime` PID-1** — расширенный `scripts/docker/model_runtime.py`, который стартует **весь** host set как children (один сервис снаружи).

Рекомендация: **hybrid** — отдельные сервисы для heavy writers (cognition, paper, TF manager, shadows) + один `assurance-runtime` для assurance ctl suite, чтобы не плодить 10 микросервисов.  
**Критерий приёмки:** `vps_stack.sh health` показывает alive все required единицы из §8.

**Запреты Plane A:**

- `REAL_EXECUTION=true`, trading API keys
- bind-mount живого Mac `data/`
- запись из dashboard/telegram в paper books
- **урезание** EQCORR / Auction / shadows / assurance из default `up`

### Plane B — Ops Surface (как `dashboard start`)

| Service | Port | Notes |
|---------|------|--------|
| `ops-api` | 8080 (smoke 18080) | `run_api.py`, **ro** data |
| `dashboard-ui` | 80 via proxy (smoke 5173→80) | `Dockerfile.prod` |
| `context-refresher` / visual | — | `run_market_context_visual_refresher.py` |
| `trade-chart` | 8765 | viewer server |

Dashboard не стартует модель и не пишет cognition/paper.

### Plane C — Telegram (sibling compose, обязателен в VPS-сборке)

`bot` + `publisher` + `redis` + `state-init`.  
Publisher: **ro** mount `btc_ml_data` → `/runtime`.  
Отдельный project `btcml-telegram` для blast-radius; операторский runbook поднимает **оба** plane.

---

## 3. Data, volumes, boot contract

| Volume | Mount | Writer |
|--------|-------|--------|
| `btc_ml_data` | `/app/data` | Plane A only |
| `btc_ml_run` | `/app/run` | Plane A |
| `btc_ml_logs` | `/app/logs` | append |
| `telegram_state` / `redis_data` | Plane C | Telegram |

Код в image; data в volume. Не монтировать весь git tree rw.

### Bootstrap (`profile: bootstrap`, one-shot)

1. Create + activate paper epoch (CTO pattern)  
2. `paper_only_contract.json` → PASSED  
3. Clear stale PID/locks  
4. Не копировать Mac epoch/WAL blindly  

### Health (полная модель)

| Layer | Evidence |
|-------|----------|
| cognition / paper | health JSON + paper_only / no real execution |
| timeframe_manager | pid alive; 4 TF state present; anti-saw rails enabled in code |
| stp_be33 | `STP_BE33_RUNNING_SHADOW_ONLY` |
| structural / auction / **eqcorr** | shadow health alive (degraded early OK, process must run) |
| assurance summary | ctl health / summary artifact |
| ops-api | `GET /health` 200 |
| stack | `vps_stack.sh health` — **fail если любой required unit down** |

---

## 4. Images & build

| Image | Role |
|-------|------|
| `btc-ml-runtime:<tag>` | полный model codepath (live + shadows + assurance) |
| `btc-ml-ops-api:<tag>` | dashboard backend |
| `btc-ml-dashboard-ui:<tag>` | nginx SPA |
| `btcml-telegram-ops:<tag>` | sibling bot |

Pin tag = `vYYYYMMDD` + git sha. Secrets вне image.

---

## 5. Networking & reverse proxy

```
Internet → TLS proxy
  /        → dashboard-ui
  /api /ws → ops-api
  /chart   → trade-chart
  (no public) model + telegram redis
```

Firewall: 80/443 + SSH.

---

## 6. Security / DevOps canons

1. Paper-only contract + entrypoint guards  
2. Non-root, `cap_drop: ALL`, `no-new-privileges`  
3. API/UI `read_only` + tmpfs  
4. Mem/CPU limits (особенно cognition + structural + eqcorr)  
5. Log rotation  
6. Restart: model `on-failure` (capped); ops `unless-stopped`  
7. Secrets via `_FILE` / Docker secrets  
8. Projects: `btcml-model` + `btcml-telegram`  
9. Smoke on isolated volume / non-prod ports  
10. Volume backup + rollback by image tag  

---

## 7. Operator UX (один выход на полную модель)

```bash
./scripts/deploy/vps_stack.sh bootstrap   # once
./scripts/deploy/vps_stack.sh up          # FULL model + dashboard — no component flags
./scripts/deploy/vps_stack.sh health      # fails if any required unit missing
./scripts/deploy/vps_stack.sh down

# Telegram (required sibling)
./scripts/deploy/vps_telegram.sh up
```

Запрещено: `up --profile without-eqcorr`, скрытые exclude-листы, «MVP без Auction».

---

## 8. Full parity matrix (accept = all ✅ default)

| Host unit | Docker default | Notes |
|-----------|----------------|-------|
| `run.py` | ✅ | canonical runtime |
| `collector_watchdog` | ✅ | |
| `context_refresh_daemon` | ✅ | |
| `timeframe_manager` (4 TF + **Anti-Saw**) | ✅ | traders STOPPED |
| `live1a` | ✅ | |
| `live1b` | ✅ | |
| `intrabar_supervisor` | ✅ | |
| `stp_be33` | ✅ | position management shadow |
| `trd_outcome2` | ✅ | start with stack; status may be soft |
| `shadow_auction` | ✅ | |
| `shadow_structural_protection` | ✅ | Stop/Take |
| `shadow_economic_correlation` (**EQCORR**) | ✅ | **always on** |
| assurance suite (7 ctl) | ✅ | |
| dashboard api + ui | ✅ | |
| visual refresher + trade chart | ✅ | |
| telegram bot + publisher | ✅ sibling | |

Drift gate: CI / smoke сравнивает alive set с этим списком.

---

## 9. Migration plan

| Phase | Work | Exit |
|-------|------|------|
| **D0** | Port CTO → `deploy/vps/` in main | ✅ tree + docs under `deploy/vps/` |
| **D1** | SERVICE_GRAPH = **полный** host set (вкл. EQCORR, Auction, BE33, TF+anti-saw, assurance) | ✅ `SERVICE_GRAPH.md` + default compose (no exclude profiles) |
| **D2** | Image + named volumes; no whole-repo bind | cold start empty volume (next) |
| **D3** | Dashboard + chart + refresher | UI + `/health` |
| **D4** | Telegram на shared volume ro | bot sees model health |
| **D5** | Smoke: **все** required units alive + paper-only proof | `VPS_FULL_MODEL_VALIDATED` |
| **D6** | TLS proxy + backup runbook | VPS cutover ready |

**Не делать:** урезанный MVP; archive VPS revive; Telegram внутри model compose; root Aug-9 compose as-is.

---

## 10. Risks

| Risk | Mitigation |
|------|------------|
| Host↔Docker process drift | Generated checklist from `MODEL_CTLS` + model_start extras; CI |
| Heavy shadows (EQCORR/Auction/STP) on small VPS | Size VPS for full set; mem limits; do not drop services |
| Fresh volume / no exact ticks | Shadows may be DEGRADED — **process всё равно must run**; no OHLCV fake |
| Dual writers Mac+VPS | One writer per volume |

---

## 11. Immediate next step

1. ~~**D0** — port CTO pack → `deploy/vps/`~~ ✅  
2. ~~**D1** — SERVICE_GRAPH = full §8 (EQCORR included)~~ ✅  
3. **D2** — cold-start image/volume validation; fix any read-only / auction storage / collector venv gaps  
4. Isolated smoke — full model (`vps_stack.sh smoke`), not subset  

---

## 12. References

- Host truth: `scripts/btc_ml_host.py` (`model_start`, `MODEL_CTLS`, `model_status`)  
- Anti-Saw: `src/btc_ml/trading/timeframe_manager.py`  
- Local prototype: `compose.yaml`, `scripts/docker/model_runtime.py`  
- CTO pack: `../btc-ml-cto-deployment-pack/deploy/cto/`  
- Telegram: `../btc-ml-telegram-bot/services/telegram-ops-bot/`  
