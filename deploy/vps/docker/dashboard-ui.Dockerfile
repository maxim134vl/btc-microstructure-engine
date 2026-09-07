# syntax=docker/dockerfile:1
# Frontend built inside Docker — no host node_modules / dist required.
# Build context: repository root.

FROM node:20-alpine AS build
WORKDIR /app
COPY dashboard/frontend/package.json dashboard/frontend/package-lock.json ./
RUN npm ci
COPY dashboard/frontend/ ./
# Docker/nginx serves SPA and proxies /api + /ws to ops-api on the compose network.
# Bake relative bases so the browser never hardcodes host :8080.
ENV DASHBOARD_USE_VITE_PROXY=1 \
    VITE_DASHBOARD_API_BASE=/api/v1
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY dashboard/frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
