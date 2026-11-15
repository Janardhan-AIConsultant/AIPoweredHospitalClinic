# Bindu Clinic — Hospital & Appointment Platform

AI-assisted clinic website: doctor discovery, real-time availability, guest booking,
Grok-powered appointment chatbot (backend-controlled tools), WhatsApp confirmations
through a transactional outbox. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Status:** all 15 build phases are complete and verified locally (241 backend tests, 62 frontend tests, 27 browser
end-to-end tests in two modes). Every external integration (xAI/Grok, ChromaDB + embeddings, WhatsApp Cloud API) runs in
**MOCK** mode until credentials are set; `GET /health/ready` reports the active mode of each. **Nothing has been deployed and
no live integration has been exercised**: read [docs/READINESS.md](docs/READINESS.md) (blockers, risks, first-live
verification plan) before going to production.

| Document | Contents |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | components, flows, decisions and deviations from the original plan |
| [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md) | schema, double-booking protection, PII, retention, migrations |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Vercel + Neon + GitHub setup, environment variables, release and rollback |
| [docs/READINESS.md](docs/READINESS.md) | requirements traceability, launch checklist, risk register |

## Layout
- `backend/` FastAPI (Python 3.12 on Vercel; 3.11 also tested) — independent project
- `frontend/` Next.js 16 — independent project
- `docs/` architecture and design documents

## Backend quick start
```
cd backend
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements-dev.txt
copy .env.example .env
pytest --cov=app
uvicorn app.main:app --reload
```
Local Postgres: `docker compose up -d postgres`.

## Backend file responsibilities (core; see ARCHITECTURE.md for the full module map)
| File | Responsibility |
|---|---|
| app/main.py | App factory: CORS, middleware, handlers, routers |
| app/core/config.py | Validated settings; fails fast in production; reports mock/live modes |
| app/core/logging.py | JSON logs, request-id, PII masking |
| app/core/middleware.py | Request id, access log + duration, size limit, security headers |
| app/core/exceptions.py | Domain errors and safe, centralised error responses |
| app/api/routes/health.py | Liveness / readiness |
| app/utils/pii.py, phone.py, timezone.py | Masking, E.164 validation, UTC/IST conversion |

## Database (Phase 3)
```
# local Postgres: docker compose up -d postgres
set MIGRATION_DATABASE_URL=postgresql://clinic:clinic_dev_only@localhost:5432/clinic
alembic upgrade head            # from backend/
python -m app.database.seed     # demo doctors (needs DATABASE_URL)
pytest                          # integration tests run on TEST_DATABASE_URL (DROPS its public schema;
                                # refuses *.neon.tech hosts)
```
See [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md).

## Booking API (Phase 5)

| Endpoint | Purpose |
| --- | --- |
| `GET /doctors/{id}/slots?date=YYYY-MM-DD` | Bookable slots (honours schedules, breaks, leave, existing bookings, lead time, horizon) |
| `POST /appointments` | Guest booking. Optional `Idempotency-Key` header makes retries safe |

Concurrency: booking locks the doctor row (`SELECT ... FOR UPDATE`), recomputes slots under the lock, and relies on the
`ex_appointments_no_overlap` constraint as the final guarantee. Deadlocks/overlaps surface as `409 slot_unavailable`.
Cancel/reschedule exist at service level; their public endpoints arrive with OTP patient verification.

## Frontend (Phase 6)

```bash
cd frontend
cp .env.example .env.local      # NEXT_PUBLIC_API_URL (backend base URL)
npm install
npm run dev                     # http://localhost:3000
npm run lint && npm run typecheck && npm test && npm run build
```

Routes: `/` (landing), `/doctors` (search + specialty filter), `/doctors/[id]` (profile + date → time → details → confirmation).
Next.js 16 with Cache Components: pages that read the API stream inside `<Suspense>`, so `npm run build` needs no backend.
`NEXT_PUBLIC_API_URL` is inlined at build time; set it for each deployment. The backend's `FRONTEND_URL` must match the site origin (CORS).

## Chatbot (Phase 7)

`POST /chat` runs one assistant turn; `POST /chat/confirm` performs a booking the *patient* confirmed.

```
user text -> input guardrails (emergency > injection > medical, deterministic, no LLM)
          -> LLM <-> read-only tools (list_specializations, find_doctors, get_available_slots, propose_booking)
          -> output guard (prompt-leak canary, links, dosage-like text) -> reply (+ signed booking proposal)
```

- **Mock by default.** With no `XAI_API_KEY` + `XAI_MODEL` the deterministic `MockLLM` runs (same tool protocol).
- **Live Grok via LangChain.** Set `XAI_API_KEY` and `XAI_MODEL` (e.g. a current Grok model name from your xAI console) in `backend/.env`; `GrokLLM` uses `langchain-xai` (`ChatXAI`). It is tested with a fake chat model only and has not yet been run against the real API; `/health/ready` shows `llm: live` once both are set.
  `/health/ready` reports `llm: mock|live`. The Grok adapter (`app/ai/llm.py`) is unit-tested against a fake transport only
  and has **not** been run against the real xAI API yet.
- **The model cannot book.** `propose_booking` only returns a signed, 10-minute proposal. The UI posts it with the patient's own
  name/phone to `/chat/confirm`, which calls the normal booking service (idempotent per proposal).
- **PII never reaches the model.** Phones/emails in chat text are masked before the LLM call; booking details go through the confirm form.
- **Requires** `JWT_SECRET_KEY` (signs proposals). Rate limits (20 chat / 10 confirm per minute per IP) are in-memory, per instance.

## Clinic information RAG (Phase 8)

- The chatbot has a read-only `clinic_info` tool that retrieves passages from `backend/knowledge/*.md` (hours, address, booking and cancellation policy, fees, privacy, FAQs). **The current content is placeholder text: replace it with the clinic's real details before launch.**
- Pipeline: markdown → section chunks (`app/rag/chunking.py`) → embeddings → vector store → top-3 passages above a similarity threshold. Passages are treated as data; the system prompt forbids following instructions inside them, and the output guard still applies to replies.
- **Mock mode (default, no `CHROMA_URL`)**: deterministic hashing embedder + in-memory store built from `knowledge/` at first use. Lexical matching only.
- **Live mode (`CHROMA_URL` set)**: Hugging Face embeddings (`HUGGINGFACE_MODEL`) + `ChromaVectorStore`. Install the optional `chromadb` and `sentence-transformers` packages, then run `python -m app.rag.ingest` to populate the collection (never done at request time). The Chroma and HF adapters are tested against fakes only and have **not** been run against a real Chroma server or model.

## WhatsApp notifications (Phase 9)

- **Transactional outbox:** booking, cancellation and rescheduling add a `notification_outbox` row in the *same* database transaction (only when the patient consented), so a message exists if and only if the change commits. `dedupe_key` (`<template>:<appointment id>`) makes enqueueing idempotent. Payloads hold only patient first name, doctor, date, time and reference. Phone numbers stay Fernet-encrypted in the row.
- **Drain worker:** `GET|POST /internal/cron/notifications` (header `Authorization: Bearer $CRON_SECRET`, which is what Vercel Cron sends) queues reminders for appointments starting within 24h and sends due messages (batch of 20, 20 s budget). Rows are claimed with `FOR UPDATE SKIP LOCKED`; failures retry with backoff 1m, 5m, 15m, 1h, 6h, then become `DEAD`; permanent errors (HTTP 4xx other than 408/429) go straight to `DEAD`; rows stuck in `PROCESSING` for over 5 minutes are reclaimed. Delivery is at-least-once. Every attempt is recorded in `notification_logs`.
- **Webhook:** `GET /webhooks/whatsapp` answers Meta's verification handshake; `POST` requires a valid `X-Hub-Signature-256` HMAC (rejected when `WHATSAPP_APP_SECRET` is unset), records `sent/delivered/read/failed` statuses once each, and treats a `STOP` reply as opt-out (clears consent on the patient and their future appointments).
- **Mock vs live:** without `WHATSAPP_ACCESS_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` a mock sender is used: rows are marked `SENT` with a `mock-…` id and nothing leaves the server. The Cloud API adapter is tested against a fake transport only, and the template names (`appointment_confirmation`, `appointment_cancelled`, `appointment_rescheduled`, `appointment_reminder`, each with 5 body variables: name, doctor, date, time, reference) must still be created and approved in Meta Business Manager.
- **Not scheduled yet:** the cron trigger itself (Vercel `vercel.json` / GitHub Actions) is configured in the deployment phase.

## Patient self-service with WhatsApp OTP (Phase 10)

Guests book without an account; to **view, cancel or reschedule** they verify their mobile number.

| Endpoint | Purpose |
| --- | --- |
| `POST /patient/otp/request` `{phone}` | Always answers `202` with the same text. A code is sent only if the number has appointments. |
| `POST /patient/otp/verify` `{phone, code}` | Returns a 15-minute bearer token (`role=patient`, subject = phone hash). |
| `GET /patient/appointments` | Own appointments from the last 30 days onward (max 50). |
| `POST /patient/appointments/{ref}/cancel` | Cancel an own, active, future appointment. |
| `POST /patient/appointments/{ref}/reschedule` `{date, start_time}` | Atomically move to another slot with the same doctor (new reference). |

- **Code handling:** 6 random digits, valid 10 minutes, single use, stored only as an HMAC bound to the challenge and phone. Sent directly through the WhatsApp sender (not the outbox), never logged. At most 5 wrong guesses per code, 3 codes per number per 15 minutes, 60 s apart; plus per-IP limits (in-memory, per instance).
- **No enumeration:** unknown numbers, throttled requests and send failures look identical to the caller; "not yours" and "does not exist" appointments both return `404`.
- **Schema:** migration `0002` adds `otp_challenges`. **It has been applied to the local/test database only, not to Neon production.**
- **Template to approve in Meta:** `otp_verification` (authentication category, one body variable plus a copy-code button carrying the same code). In mock mode the code is only visible to tests; there is no dev backdoor.
- **Not built yet:** no frontend "My appointments" page. The 4-hour cancellation notice in the clinic FAQ is a request, not enforced. A patient's token is not revocable before its 15-minute expiry.

## Staff authentication, RBAC and dashboards (Phase 11)

Roles: `ADMIN` and `DOCTOR` (patients use OTP, see Phase 10). Migration `0003` adds `refresh_tokens`; **it has not been applied to Neon**.

- **Login:** `POST /auth/login` returns a 15-minute access token in the body (keep it in memory in the frontend) and sets a rotating 7-day refresh token as an `HttpOnly`, `Secure` (staging/production), `SameSite=None` cookie scoped to `/auth`. `POST /auth/refresh` and `/auth/logout` need that cookie plus a custom `X-CSRF-Token` header (forces a CORS preflight that only `FRONTEND_URL` passes). Reusing a rotated refresh token revokes the whole token family. 5 failed logins lock an account for 15 minutes; unknown email and wrong password are indistinguishable.
- **RBAC:** every staff request re-checks the user in the database, so deactivation and role changes apply immediately, even to unexpired access tokens. Patient tokens never work on staff routes and vice versa. Doctors are always scoped to their own appointments and leave ("not yours" = 404).
- **Admin API (`/admin`):** stats, appointment list (filters, pagination, masked phones), cancel, mark `COMPLETED`/`NO_SHOW` (only after the start time), doctor fee/bio/active edits, leave, user management (create doctor/admin, deactivate, which also revokes sessions), audit log.
- **Doctor API (`/doctor`):** own appointments, cancel, complete/no-show, own leave.
- **Audit:** logins, lockouts, refresh-token reuse, user, doctor, leave and appointment changes are recorded with the actor, never with phone numbers or secrets.
- **First admin:** `ADMIN_PASSWORD=... python -m app.database.create_admin you@example.com` (min 12 chars with upper/lower case and a digit).
- **Decision still open:** adding leave over days that already have bookings does **not** cancel them. The API reports `affected_appointments` and staff cancel (and patients get notified) explicitly.
- **Not built:** schedule editing, password reset / change, MFA, and the dashboard UI itself.

## Frontend: patient portal and staff dashboards (Phase 12)

- **`/my-appointments`**: mobile number → WhatsApp code → list of own appointments with inline cancel (explicit confirmation) and reschedule (date → live slots → pick). The patient token lives in component state only, so reloading the page asks for a new code.
- **`/staff/login`** and **`/staff`**: sign-in and role-based dashboards (not indexed by search engines, linked only from the footer). The 15-minute access token is kept **in memory**, never in `localStorage`; the HttpOnly refresh cookie restores the session on reload. Concurrent refreshes share one request (refresh tokens are single use). A 401 triggers one refresh and a retry, then sends the user to sign in.
  - Admin: overview (today, upcoming, message-queue health), appointments (filters, complete / no-show / cancel with confirmation), doctors (fee, activate/deactivate) and leave with a warning when appointments fall inside the leave, audit log.
  - Doctor: own appointments and own leave only.
- **Local dev note:** the frontend (`localhost:3000`) and API (`localhost:8000`) are the same *site*, so the cookie works with `SameSite=Lax`. In production they are on different sites and the cookie is `SameSite=None; Secure`, which needs HTTPS on both. **This cross-site cookie flow has not been exercised in a real browser yet.**
- **Not built:** user management UI (use the API / `create_admin` script), schedule editing, password change. Only jsdom-level tests exist; there is no Playwright run and no visual check.

## Hardening, security review and end-to-end tests (Phase 13)

**Run the browser suite** (real Chromium, real API + Postgres, mock WhatsApp/LLM): create a local database once with `CREATE DATABASE clinic_e2e;` on the docker Postgres, then `cd frontend && npm run e2e`. It builds the frontend, starts the API on `:8100` and the site on `:3100`, resets `clinic_e2e` (the setup refuses any database whose name does not end in `_e2e`), and runs 25 tests: guest booking, OTP login + reschedule + cancel, staff and doctor flows (including HttpOnly cookie, session restore, masked phones, cross-role refusal), the chatbot guardrails, axe accessibility (WCAG 2.0/2.1 A and AA) on the main pages, CSP/console errors, security headers and CORS. `backend/tests/e2e_server.py` is used only by this suite: it swaps in the mock sender and exposes the latest OTP so the browser test can log in; it is not part of the deployed app.

**Fixed in this phase**
- Request bodies are now capped on the bytes actually received, so chunked uploads without `Content-Length` can no longer bypass the limit (`app/core/body_limit.py`).
- The WhatsApp webhook authenticates the signature *before* any database session or key setup is touched.
- Frontend security headers: CSP (`frame-ancestors 'none'`, `object-src 'none'`, `connect-src` limited to the API origin), `nosniff`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, HSTS, no `X-Powered-By`; staff pages are `no-store`.
- New tests: logs never contain names, phone numbers, e-mails, reasons or passwords; access tokens and booking proposals cannot be swapped; foreign-key or `alg=none` JWTs are rejected; API docs are hidden in production; secrets never appear in settings repr.

**Dependency audit:** `pip-audit` finds nothing in `requirements.txt`; `npm audit --omit=dev` finds nothing. `npm audit` still lists 8 *moderate* findings, all in the ESLint toolchain (`minimatch` via `typescript-eslint`), which ships nowhere; the suggested fix is a breaking `--force` downgrade, so it is left alone.

**Known limitations (honest list)**
- CSP keeps `script-src 'unsafe-inline'` because Next.js hydration needs inline scripts; removing it needs a per-request nonce proxy.
- The rate limiter is per instance, and the client IP comes from `X-Forwarded-For`, which is only trustworthy behind Vercel's proxy.
- Accessibility was checked automatically in light mode on five pages; automated checks cover only part of WCAG, and dark mode, screen readers and keyboard-only use were not tested manually.
- Only Chromium, desktop viewport. The cross-site cookie (`SameSite=None; Secure`) cannot be tested on `localhost`; the e2e run proves the same-site flow.
- Real Grok, Chroma, WhatsApp Cloud and Neon-with-new-migrations remain unverified.

## Containers, CI/CD and deployment (Phase 14)

Full runbook: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** (topology, every environment variable, GitHub secrets, release flow, rollback, what is and is not verified).

- **Docker:** `backend/Dockerfile` (Python 3.12, non-root, health check) and `frontend/Dockerfile` (Next.js standalone, non-root). `docker compose --profile full up --build` starts PostgreSQL, applies migrations, then the API (`:8000`) and the web app (`:3000`).
- **CI (`.github/workflows/ci.yml`):** backend lint + format + mypy + tests on PostgreSQL (coverage gate 85%) + migration drift/reversibility (`alembic check`, downgrade, upgrade) + `pip-audit`; frontend lint, types, unit tests, build, `npm audit`; Playwright end-to-end in two modes (direct, and same-origin `/api` proxy).
- **CD (`.github/workflows/deploy.yml`):** after CI on `main` (with an optional manual approval): migrate Neon, deploy API, deploy web, smoke test.
- **Notifications trigger:** Vercel Cron (daily, the Hobby limit) plus a GitHub Actions schedule every 5 minutes. In production the drain refuses to run with the mock WhatsApp sender, so queued messages are never marked sent without being sent.
- **Recommended topology:** two Vercel projects, with the browser reaching the API through the web app's `/api` rewrite so the refresh cookie is first-party (`AUTH_COOKIE_PATH=/api/auth`, `AUTH_COOKIE_SAMESITE=lax`).
- **Nothing has been deployed.** The workflows have never run on GitHub and the Vercel configuration has not been exercised against a real Vercel account.

## Retention, embeddings and the privacy page (Phase 15)

- `POST|GET /internal/cron/notifications` now also purges expired OTP challenges (1 day), refresh tokens (7 days after expiry / 30 after revocation) and finished outbox rows (90 days). Appointments, patients and audit logs are never purged automatically.
- Live RAG embeds through the Hugging Face **Inference API** when `HUGGINGFACE_API_TOKEN` is set (no torch in the serverless bundle); the local `sentence-transformers` embedder is only for offline ingestion. Neither has been run against the real service, and `chromadb-client` still has to be added to `requirements.txt` when Chroma goes live.
- `/privacy` is a **draft** that describes what the system actually does; the clinic must complete and legally review it.
