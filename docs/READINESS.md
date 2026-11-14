# Readiness review (Phase 15)

Date of review: end of the 15-phase build. "Verified" means executed in this repository; "unverified" means written to the vendor's documentation but never run against the real service.

## Verdict

**Ready for a staging deployment with every integration in mock mode. Not ready for real patients** until the blockers below are cleared. Nothing has been deployed, and no live xAI, Chroma, WhatsApp, Vercel or GitHub Actions run has happened. The code, tests and configuration are in place; what is missing is accounts, credentials, clinic content and a first real deployment to confirm the vendor-specific parts.

## Requirements traceability

| Requirement | Where | Evidence | Status |
| --- | --- | --- | --- |
| Guest booking, no account | `services/booking.py`, `booking-flow.tsx` | concurrency, idempotency and e2e tests | **Done, verified** |
| No double-booking | row lock + recomputed slots + exclusion constraint | concurrency and race tests on real PostgreSQL | **Done, verified** |
| Chatbot with backend-controlled tools | `ai/` | model has 5 read-only tools; booking needs a human-submitted form; tests prove the model never sees PII or the proposal | **Done with mock model; live Grok unverified** |
| Medical + prompt-injection guardrails | `ai/guardrails.py` | deterministic, run before the model; unit + e2e tests | **Done, verified** (a real model may still behave unexpectedly) |
| PII protection | `core/security.py`, masking, logs | encrypted phone/email, masked staff views, log-privacy test, no tokens in browser storage | **Done, verified** |
| Clinic info via RAG (Chroma) | `rag/` | mock path verified; Chroma and HF adapters tested against fakes only | **Mock verified; live unverified** |
| WhatsApp via transactional outbox | `notifications/` | outbox, retries, dedupe, webhook signature, STOP, production safety guard | **Done; Cloud API unverified** |
| OTP patient retrieval, cancel, reschedule | `services/otp.py`, `routes/patient.py`, `patient-portal.tsx` | throttling, lockout, no enumeration, e2e flow | **Done, verified** (code delivery unverified live) |
| RBAC dashboards (admin, doctor) | `routes/admin.py`, `doctor_portal.py`, `components/staff/` | role matrix, immediate deactivation, scope tests, e2e | **Done, verified** |
| Audit trail | `services/audit.py` | audited actions, PII-free | **Done, verified** |
| Tests | see below | | **Done** |
| CI/CD | `.github/workflows` | YAML valid; same commands run locally | **Written; never run on GitHub** |
| Docker | Dockerfiles, compose `full` profile | built and run end to end | **Done, verified** |
| Vercel hosting + Neon | `vercel.json`, DEPLOYMENT.md | | **Written; unverified** |
| Docs | README, ARCHITECTURE, DATABASE_DESIGN, DEPLOYMENT, this file | | **Done** |

## Test inventory (all passing at review time)

- Backend: **241** tests (unit + integration on real PostgreSQL), 90% line coverage, ruff + format + mypy (strict) clean, `pip-audit` clean, `alembic check` clean. Also run on Python 3.12, Vercel's version.
- Frontend: **62** unit/component tests, lint, tsc and production build clean, `npm audit --omit=dev` clean (8 moderate findings in dev-only ESLint tooling).
- End to end: **27** Playwright tests (Chromium) in two modes (direct and same-origin proxy): booking, OTP, staff and doctor flows, chatbot guardrails, axe accessibility, CSP/console, security headers, CORS.

## Launch checklist

### Blockers (do not accept real patients before these)
1. **Clinic content.** Replace the placeholder text in `backend/knowledge/*.md` (hours, address, policies), complete and legally review `/privacy`, and add the clinic's real doctors. **The Neon production database still contains five seeded demo doctors** (`is_demo`); deactivate or delete them first or the public site will let people book them.
2. **Secrets.** Generate `JWT_SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, `PHONE_HASH_KEY`, `CRON_SECRET` and store them in Vercel/GitHub. Back up `FIELD_ENCRYPTION_KEY` and `PHONE_HASH_KEY` somewhere safe: if either is lost or changed, stored phone numbers cannot be decrypted or looked up. There is no key-rotation tooling.
3. **Migrations on Neon.** Production is at migration 0001 as last observed; 0002 (OTP) and 0003 (refresh tokens) are applied only by the Deploy workflow or by hand with `alembic upgrade head` using the direct (unpooled) URL.
4. **First real deployment and smoke test** (API and web projects, `/health/ready`, staff login and reload, booking). Specifically confirm: Vercel finds the FastAPI app and bundles `knowledge/`; the cron registers; and the API sees distinct client IPs behind the web project's `/api` rewrite (the rate limiter keys on `X-Forwarded-For`).
5. **First admin and doctor accounts** via `python -m app.database.create_admin` and `POST /admin/users`.
6. **Live WhatsApp.** Approve the five templates, add the credentials, register the webhook, then send a real confirmation, a delivery receipt, a `STOP`, and an OTP. Until credentials exist, queued messages stay `PENDING` and OTP codes are not delivered, so patients cannot use "My appointments".
7. **Data governance.** The clinic must decide appointment-record retention and how patient access/erasure requests are handled; there is no export or erasure tooling.
8. **Backup and restore drill** on Neon (point-in-time restore into a branch), and write down who does it.

### Strongly recommended before launch
- **Live Grok check** with the real model name: tool calling works, the answers stay short and on-topic, the guardrails still catch the red-team prompts (the e2e prompts are a starting set), and responses stay within the 30 s function limit.
- **Live Chroma + embeddings.** Add `chromadb-client` (or `chromadb`) to `backend/requirements.txt`, set `CHROMA_URL` and `HUGGINGFACE_API_TOKEN`, run `python -m app.rag.ingest`, then compare answers with the mock. The mock matches words only; live retrieval quality is unknown.
- **Monitoring.** Only structured logs exist. Add an uptime check on `/health/ready` and an alert on dead messages (`GET /admin/stats` → `notifications.DEAD`), and consider error tracking.
- **Admin protection.** Admin accounts have a password only (12+ characters, lockout after 5 failures). There is no MFA and no password change or reset: a locked-out or forgotten account needs a database fix.
- **A real-browser pass on phones**, in dark mode, with a screen reader and keyboard only; automated checks cover part of WCAG only. Test in Safari and Firefox too (only Chromium was run).
- Enforce the 4-hour cancellation notice if the clinic wants it (it is only text in the FAQ today).

### Later
Schedule editing in the admin UI, user-management UI, chat feedback (table exists, no endpoint), doctor notifications, a global rate limiter (Redis/Postgres), per-request CSP nonce, multi-clinic support.

## Risk register

| Risk | Impact | Mitigation today | Residual |
| --- | --- | --- | --- |
| Lost or rotated encryption/hash key | Patients' phones unreadable; lookups and OTP fail | documented in DEPLOYMENT.md | High if keys are not backed up |
| Rate limits are per instance; IP from `X-Forwarded-For` | Weak brute-force and cost protection; possibly all users in one bucket behind the proxy | OTP/login also limited per account/number in the database | Medium until verified on Vercel |
| GitHub schedule is best-effort and pauses after 60 idle days; Hobby cron runs once a day | Late or missing reminders | manual workflow trigger; guard that leaves messages `PENDING` rather than lose them | Medium; Pro plan removes it |
| At-least-once delivery | A patient may occasionally get a duplicate message after a crash | dedupe key per appointment and event | Low |
| Leave added over booked days | Patients stay booked with an absent doctor | API reports `affected_appointments`; staff cancel explicitly | Medium: process decision for the clinic |
| Live model misbehaves or tool-calls fail | Poor or blocked chat | guardrails before the model, output filter, safe fallbacks, mock fallback by configuration | Unknown until tested live |
| Access tokens cannot be revoked before expiry (15 min); no MFA | Short window after account compromise | deactivation is checked on every staff request; refresh tokens revoke at once | Low–Medium |
| `script-src 'unsafe-inline'` in the CSP | Weaker XSS defence-in-depth | no HTML injection sinks; strict headers otherwise | Low |
| Demo doctors in production database | Real bookings against fake doctors | checklist item 1 | High until removed |
| Single timezone and single clinic | Not suitable for multi-location use | by design | Accepted |
| Vendor-specific code never run live (Grok, Chroma, HF, WhatsApp, Vercel, Actions) | Surprises at first go-live | adapters isolated behind interfaces, tested against fakes, mock fallback | Medium; this is what the live verification below is for |

## First live verification plan

Do these one at a time, in this order, each on staging first; stop and fix before the next.
1. Neon (staging branch): `alembic upgrade head`, `/health/ready` shows `database: ok`.
2. Deploy API and web; staff login, reload, logout; check the client IP seen by the API.
3. Grok: set `XAI_API_KEY` and `XAI_MODEL`; run the chat scenarios (specialties, a doctor's slots, a prepared booking, an emergency, a dosage question, a prompt-injection attempt).
4. Chroma + embeddings: ingest, then ask the FAQ questions.
5. WhatsApp: templates → one confirmation, one OTP, one `STOP`, one delivery receipt; watch `GET /admin/stats`.
6. Cron: confirm both triggers reach `/internal/cron/notifications`.
7. Backup restore drill; remove demo data; switch DNS.
