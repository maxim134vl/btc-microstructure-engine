# Запуск всей модели на другом ПК

Paper-only Docker-стек. Не host `./scripts/btc_ml`. Не архивный VPS. Не копировать живой `data/` с Mac.

Ветка: `memory/canonical-system`.  
Операторский вход: `./scripts/deploy/vps_stack.sh`.  
Compose: `deploy/vps/docker-compose.yml`.

## Железо (обязательно)

На M1 8 ГБ стек **не живёт** вместе с документами: Docker 4 ГБ + 8 ядер, swap 13–16 ГБ, ops-api отвечает 16 с, paper зависает на bookTicker.

| | Минимум | Норма |
|---|---|---|
| RAM хоста | **16 ГБ** | 32 ГБ |
| RAM Docker | **8 ГБ** | 12 ГБ |
| CPU Docker | 4 ядра, **не все** ядра хоста | 6 из 8 |
| Диск | 80 ГБ свободно | 200 ГБ SSD |
| ОС | Linux x86_64 / Apple Silicon с Docker Desktop | Ubuntu 22.04+ |

`vps_stack.sh doctor` ругается, если у Docker меньше ~8 ГиБ.

WAL paper растёт быстро (сотни МБ → гигабайты). Не копировать `Docker.raw` со старой машины (у нас был 228 ГБ).

## Что не делать

- Не bind-mount живого Mac `data/` в новый ПК.
- Не тащить эпоху `PER_TF_EQUITY_1PCT_V1_VPS_*` как «миграцию».
- Не включать HL vault и archive в одном стеке.
- Не коммитить `.env` и `config/hl-testnet.secrets.env`.
- Не возвращать hold=3, bar-count anti-saw, наследование M15 на старшие ТФ.
- Не `docker rm` контейнеров «для оптимизации» — только `stop` / `start`.

## 1. Софт

```bash
git --version          # 2.40+
docker --version       # Engine 24+ / Desktop 4.x
docker compose version # v2
python3 --version      # 3.11+
```

Linux: пользователь в группе `docker`. Mac: Docker Desktop → Settings → Resources: RAM ≥ 8 ГБ, CPU не все ядра хоста.

## 2. Репозиторий

```bash
git clone https://github.com/maxim134vl/btc-microstructure-engine.git btc-ml
cd btc-ml
git checkout memory/canonical-system
git pull --ff-only
```

Внутренний зеркало: `gitea` `https://gitea.fonte.kaz/skramovskiyin/btc-microstructure-engine.git`.

Telegram — **отдельный** репозиторий рядом (`../btc-ml-telegram-bot`). Без него модель стартует, бот нет.

## 3. Env

```bash
cp deploy/vps/.env.example deploy/vps/.env
```

Проверить в `.env`:

```
PAPER_ONLY=true
REAL_EXECUTION_ENABLED=false
EXECUTION_ENABLED=false
COMPOSE_PROJECT_NAME=btcml-vps
VPS_VOLUME_NAME=btc_ml_data_vps
```

Порты по умолчанию: OPS `18080`, дашборд `15173`, график `18765`.

## 4. Сборка и новый paper-epoch

Новая машина = **новая эпоха** в named volume. Bootstrap не копирует живую книгу.

```bash
./scripts/deploy/vps_stack.sh doctor
./scripts/deploy/vps_stack.sh bootstrap
./scripts/deploy/vps_stack.sh build
./scripts/deploy/vps_stack.sh up
./scripts/deploy/vps_stack.sh health
./scripts/deploy/vps_stack.sh status
```

Первый `health` может быть `starting` 1–3 минуты (`start_period`).

Остановить, **том сохранить**:

```bash
./scripts/deploy/vps_stack.sh down
```

## 5. Что поднимает `up`

Пишет в volume `btc_ml_data_vps` → `/app/data`.

**Торговля (без этого paper слепой):**

| Сервис | Роль |
|--------|------|
| `collector-watchdog` | рынок |
| `canonical-runtime` | `run.py` |
| `cognition-runtime` | LIVE1A / контекст |
| `context-refresh-daemon` | lifecycle баров |
| `paper-manager` | LIVE1B книги + BBO/aggTrade |
| `timeframe-manager` | S4.1, 4 ТФ, сила, path-density пила |
| `intrabar-supervisor` | надзор |

**Картинка и отчёты (можно стопнуть, сделки живут):**

| Сервис | Порт / цена |
|--------|-------------|
| `ops-api` | `:18080` — тяжёлый, ~400 МБ + CPU |
| `dashboard-ui` | `:15173` — почти ничего, без ops-api мёртв |
| `context-refresher` | JSON графика, ~150–180 МБ, пики CPU |
| `trade-chart` | `:18765` — ~20 МБ |
| `trd-outcome2` | отчёты |

**Не в дефолтном `up` (profiles):**

| Profile | Что |
|---------|-----|
| `shadow` | EQCORR / auction / structural / BE33 |
| `hl-vault-testnet` | Hyperliquid testnet executor |
| `bootstrap` | одноразовый bootstrap |

Shadows:

```bash
docker compose --project-name btcml-vps --env-file deploy/vps/.env \
  -f deploy/vps/docker-compose.yml --profile shadow up -d
```

## 6. График без дашборда

На слабой машине дашборд тушить, график оставить.

```bash
docker compose --project-name btcml-vps --env-file deploy/vps/.env \
  -f deploy/vps/docker-compose.yml stop dashboard-ui ops-api

docker compose --project-name btcml-vps --env-file deploy/vps/.env \
  -f deploy/vps/docker-compose.yml start context-refresher trade-chart
```

`start trade-chart` / `context-refresher` **тянет `ops-api`** (`depends_on`). Сразу глушить:

```bash
docker stop btcml-vps-ops-api-1
```

График: http://127.0.0.1:18765/

## 7. Telegram (Plane C)

Не в model compose. Sibling:

```bash
./scripts/deploy/vps_telegram.sh doctor
./scripts/deploy/vps_telegram.sh up
```

Нужен `../btc-ml-telegram-bot` или `VPS_TELEGRAM_ROOT`. Без токенов бот не стартует. На 16 ГБ лучше не поднимать, пока стек не стабилен.

## 8. Hyperliquid testnet (по желанию)

Отдельный profile, секреты **не в git**.

```bash
docker compose --project-name btcml-vps --env-file deploy/vps/.env \
  -f deploy/vps/docker-compose.yml --profile hl-vault-testnet up -d hl-vault-executor
```

После проверки — `stop`, не `rm`. Ордера на testnet сами не снимаются, если выключить только контейнер.

## 9. Проверка, что модель торгует

```bash
./scripts/deploy/vps_stack.sh health
curl -fsS -m 5 http://127.0.0.1:18765/ >/dev/null && echo chart_ok
docker exec btcml-vps-paper-manager-1 \
  python -c 'import json; from pathlib import Path; h=json.loads(Path("/app/data/runtime/intrabar_paper_health.json").read_text()); print(h.get("updated_at"), h.get("current_bbo"), (h.get("execution_market") or {}).get("state",{}).get("state"), h.get("active_positions_by_timeframe"))'
docker exec btcml-vps-timeframe-manager-1 cat /app/data/runtime/timeframe_manager_health.json
```

Ждать:

- paper `execution_market.state` = `HEALTHY`, `entry_allowed=true`
- BBO `freshness_ms` порядка сотен, не минут
- менеджер пишет команды M15/M30/H1/H4

Красные флаги (уже ловили):

- `RECOVERING` + `unresolved_gap` → OPEN не исполняется
- `ping/pong timed out` / `No address associated with hostname` на `fstream.binance.com`
- paper health не обновляется минутами при живом CPU → GIL/WAL, нужен **restart paper-manager**, не вся модель
- ops-api `/api/v1/ops/snapshot` > 5 с → дашборд «завис», сделки могут быть живы

Restart только paper:

```bash
docker restart btcml-vps-paper-manager-1
```

## 10. Если ПК слабый (8–16 ГБ)

Порядок отключения, контейнеры **не удалять**:

1. `dashboard-ui` + `ops-api`
2. `hl-vault-executor`
3. `trd-outcome2`
4. при необходимости график: `trade-chart` + `context-refresher`

Оставить: collector, canonical, cognition, context-refresh-daemon, paper-manager, timeframe-manager, supervisor.

На 8 ГБ даже этот минимум душит хост. Другой ПК для модели — не «ещё один ноутбук 8 ГБ».

## 11. Где данные

| Том | Путь в контейнере |
|-----|-------------------|
| `btc_ml_data_vps` | `/app/data` |
| `btc_ml_visual_public_vps` | JSON графика |

Эпоха после bootstrap: `data/trading/paper_epochs/active.json`.  
Книги: `data/trading/intrabar_paper/<epoch_id>/books/`.

Бэкап — `docker volume` / tar тома, не git.

## Короткий чеклист

- [ ] Хост ≥ 16 ГБ, Docker ≥ 8 ГБ, CPU не все ядра
- [ ] `memory/canonical-system`, свой `.env`, paper-only
- [ ] `doctor` → `bootstrap` → `build` → `up` → `health`
- [ ] Новая эпоха, живой Mac `data/` не копировать
- [ ] График `:18765`, дашборд только если RAM позволяет
- [ ] Telegram / HL отдельно и позже
- [ ] `down` сохраняет тома; `rm` контейнеров не использовать
