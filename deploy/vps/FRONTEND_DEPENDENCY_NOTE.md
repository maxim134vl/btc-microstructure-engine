# Frontend dependency note (VPS pack)

## Build policy

- Dashboard UI is built **inside** `deploy/vps/docker/dashboard-ui.Dockerfile`
- Uses `npm ci` from `dashboard/frontend/package-lock.json`
- Does **not** require host `node_modules` or host `dist`
- VPS validation must not modify tracked frontend generated files

## npm audit (documented, not upgraded)

A cleanroom `npm audit` previously reported **two high-severity** findings in
the frontend dependency tree. This pack deliberately does **not** perform an
unreviewed major dependency upgrade.

Operators should re-run:

```bash
cd dashboard/frontend
npm ci
npm audit
```

and track upgrades separately from VPS packaging work.
