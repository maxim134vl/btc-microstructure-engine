# BTC OBS

## Сборка и push в реестр (на твоём компе)

```bash
cd monitoring/

# один раз — залогиниться в реестр
docker login http://registry.fonte.kaz

# собрать все 5 образов (linux/amd64) и запушить
# VERSION автоматически бампится в monitoring/VERSION
make push                # 1.0.0 → 1.0.1
BUMP=minor make push     # 1.0.4 → 1.1.0
BUMP=major make push     # 1.7.2 → 2.0.0
TAG=1.0.7 make push      # форс конкретного тега, VERSION не трогается

# текущая версия
make version
```

Пушится 5 образов: `btc-engine`, `btc-metrics-exporter`, `btc-health-api`,
`btc-alert-engine`, `btc-watchdog`. Все на `registry.fonte.kaz/<name>:<tag>`.

## Запуск на сервере

```bash
# ---- один раз ----
mkdir -p /opt/btc/{data,logs} && cd /opt/btc
sudo chown -R 1000:1000 data logs
docker login http://registry.fonte.kaz

# compose-файл — скопировать с локалки:
#   scp monitoring/deploy/docker-compose.prod.yml user@server:/opt/btc/docker-compose.yml

# .env — всего две переменные
cat > .env <<EOF
BTC_VERSION=1.0.1
HEALTH_API_PORT=8080
EOF

# поднять
docker compose pull
docker compose up -d
```

UI: `http://<server-ip>:8080`

## Апгрейд

```bash
# локально
make push                                       # 1.0.1 → 1.0.2

# на сервере
sed -i 's/BTC_VERSION=.*/BTC_VERSION=1.0.2/' /opt/btc/.env
cd /opt/btc && docker compose pull && docker compose up -d
```
