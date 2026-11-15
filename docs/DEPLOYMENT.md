# Deployment guide

Status legend: **verified** = executed in this repository; **unverified** = written to the vendor's documentation but not yet run against the real service (needs your accounts and credentials).

## Topology

```
Browser ──► Vercel project "web"  (Next.js, frontend/)
              │  /api/*  rewrite (same origin, first-party cookie)
              ▼
            Vercel project "api"  (FastAPI, backend/)  ──► Neon PostgreSQL
              ▲                                           ──► Groq / Pinecone / WhatsApp Cloud (when configured)
 GitHub Actions cron (every 5 min) ─┘   Meta ──► /webhooks/whatsapp
```

Two independent Vercel projects, each with its own **Root Directory** (`backend`, `frontend`). The browser talks only to the web origin; `/api/*` is rewritten to the API. That keeps the staff refresh cookie first-party, so it keeps working under Safari / Chrome third-party-cookie blocking, and no CORS is involved. (A cross-site setup with `SameSite=None; Secure` also works and is what runs when `AUTH_COOKIE_*` is left at its defaults, but it depends on third-party cookies being allowed.)

## One-time setup

1. **Neon**: use the `production` branch. Keep two URLs: *pooled* (`-pooler` host) for the running API, *direct/unpooled* for migrations.
2. **Vercel**: create two projects from the same repository.
   - `api`: Root Directory `backend`. Framework preset: FastAPI/Other. Python 3.12 is selected by `backend/.python-version`.
   - `web`: Root Directory `frontend`, Framework: Next.js.
   - Both `vercel.json` files set `git.deploymentEnabled=false`: deployments come from the *Deploy* workflow so that migrations run first. Remove that line if you prefer Vercel's own Git integration (then migrate manually before merging).
3. **Environment variables** (Vercel → Settings → Environment Variables → Production):

   | Project | Variable | Value |
   | --- | --- | --- |
   | api | `APP_ENV` | `production` |
   | api | `DATABASE_URL` | Neon **pooled** URL |
   | api | `FRONTEND_URL` | `https://<web domain>` (must be https) |
   | api | `JWT_SECRET_KEY` | `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
   | api | `FIELD_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` — **never change it afterwards**, stored phone numbers could no longer be decrypted |
   | api | `PHONE_HASH_KEY` | any long random string — **never change it afterwards**, patient lookups would break |
   | api | `CRON_SECRET` | random string; Vercel Cron sends it as `Authorization: Bearer …` |
   | api | `AUTH_COOKIE_PATH` / `AUTH_COOKIE_SAMESITE` | `/api/auth` / `lax` (same-origin proxy mode) |
   | api | `GROQ_API_KEY`, `GROQ_MODEL` (or `XAI_API_KEY`, `XAI_MODEL`) | when you have them (otherwise the mock assistant runs) |
   | api | `PINECONE_API_KEY`, `PINECONE_INDEX_NAME`, `PINECONE_INDEX_HOST` | optional |
   | api | `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` | when approved (without them messages stay `PENDING`, see below) |
   | web | `NEXT_PUBLIC_API_URL` | `/api` |
   | web | `API_PROXY_TARGET` | `https://<api domain>` |
   | web | `API_INTERNAL_URL` | `https://<api domain>` (server-side rendering calls the API directly) |

   The API refuses to start in `production` without `DATABASE_URL`, a 32+ character `JWT_SECRET_KEY`, the two PII keys, `CRON_SECRET` and an https `FRONTEND_URL`.
4. **GitHub** → Settings:
   - *Secrets*: `DATABASE_URL_UNPOOLED` (Neon direct URL), `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_API_PROJECT_ID`, `VERCEL_WEB_PROJECT_ID`, `CRON_SECRET` (same value as in Vercel).
   - *Variables*: `API_URL` (`https://<api domain>`), `WEB_URL` (`https://<web domain>`).
   - *Environments* → `production`: add yourself as a required reviewer to get a manual approval before each migration/deploy.
5. **First admin** (after the first deploy): `cd backend && DATABASE_URL=<pooled url> FIELD_ENCRYPTION_KEY=… PHONE_HASH_KEY=… JWT_SECRET_KEY=… ADMIN_PASSWORD='…' python -m app.database.create_admin you@clinic.in`, then create doctor accounts from the admin API (`POST /admin/users`).
6. **Demo data**: `python -m app.database.seed` seeds five demo doctors. Replace them with real ones before launch; they are flagged `is_demo`.
7. **WhatsApp** (when you have an approved business account): create and approve the templates `appointment_confirmation`, `appointment_cancelled`, `appointment_rescheduled`, `appointment_reminder` (5 body variables each: name, doctor, date, time, reference) and `otp_verification` (authentication template with copy-code button), then register `https://<api domain>/webhooks/whatsapp` in Meta with your verify token and app secret.
8. **Clinic knowledge**: replace the placeholder text in `backend/knowledge/*.md` with the real hours, address and policies.

## Release flow

`push to main` → **CI** (lint, types, unit + integration tests on PostgreSQL, migration drift/reversibility check, dependency audit, frontend build, Playwright in both browser modes) → **Deploy** (manual approval if configured) → `alembic upgrade head` against Neon → deploy API → deploy web → smoke test (`/health/ready` reports `database: ok`, `/doctors` renders).

**Migration policy:** the previous API version keeps serving while a migration runs, so every migration must be backward compatible: add columns/tables first, deploy code that uses them, remove old ones in a later release.

**Rollback:** application: Vercel → Deployments → *Instant Rollback* (per project). Database: prefer a forward fix; for a bad migration use Neon point-in-time restore / branch from a timestamp. `alembic downgrade -1` exists for every migration (CI proves they reverse on an empty database) but loses data written to dropped columns.

## Notification delivery schedule

The outbox is drained by `POST|GET /internal/cron/notifications` (protected by `CRON_SECRET`).

| Plan | What runs it |
| --- | --- |
| Vercel Hobby | `backend/vercel.json` cron once a day at 03:00 UTC (the most Hobby allows; delivery within ±59 min), **plus** `.github/workflows/notifications-cron.yml` every 5 minutes (GitHub's schedule is best-effort and pauses after 60 days without repository activity). |
| Vercel Pro | Change the `vercel.json` schedule to `* * * * *`; the GitHub workflow becomes optional. |

While `WHATSAPP_ACCESS_TOKEN` / `WHATSAPP_PHONE_NUMBER_ID` are missing in production or staging, the endpoint **does not drain**: queued messages stay `PENDING` instead of being marked sent by the mock sender, and are delivered once credentials exist. Check `GET /admin/stats` (messages waiting / retrying / failed) after go-live.

## Local production-like run

```
docker compose --profile full up --build     # postgres + migrations + API :8000 + web :3000
docker compose --profile full exec api python -m app.database.create_admin you@example.com
docker compose --profile full down
```

The compose file uses throw-away secrets that are only valid for this local stack.

## What has and has not been verified

| Item | Status |
| --- | --- |
| Backend tests, lint, types on Python 3.12 (Vercel's version) and 3.11 | verified |
| `alembic check` (no model/migration drift), 0001→0003 upgrade | verified (downgrade runs in CI) |
| Docker images build; non-root; migrations + API + web run together; login and refresh work | verified |
| Playwright suite, direct mode and same-origin proxy mode | verified locally |
| Workflow YAML syntax | verified; **the workflows have never run on GitHub** |
| Vercel build/deploy of either project, the Python entrypoint detection, `includeFiles` for `knowledge/`, cron registration | **unverified** (needs your Vercel account) |
| Client IP seen by the API behind the web project's rewrite (rate limiting keys on `X-Forwarded-For`) | **unverified**: check once deployed that distinct visitors are not collapsed into one IP; if they are, rate limits need a different key |
| Neon production database is at migration 0001; 0002 (OTP) and 0003 (refresh tokens) are not applied there yet | **pending** (the Deploy workflow applies them) |
| Groq/xAI, Pinecone, WhatsApp Cloud, Meta template approval | **unverified** |

## Troubleshooting

- `/health/ready` shows `database: unavailable`: wrong `DATABASE_URL`, or the Neon compute is waking up (retry); use the pooled URL on Vercel.
- Staff are logged out on every reload: cookie path/SameSite mismatch. In proxy mode the API must have `AUTH_COOKIE_PATH=/api/auth` and `AUTH_COOKIE_SAMESITE=lax`, and the web project `NEXT_PUBLIC_API_URL=/api`.
- 429 for many visitors at once: see the client-IP row above.
- Messages stuck `PENDING`: WhatsApp credentials missing (by design), or nothing calls the cron endpoint; trigger the *Notification drain* workflow manually.
