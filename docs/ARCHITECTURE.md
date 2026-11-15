# Architecture

Reflects the system as built at the end of Phase 15. Deployment details: [DEPLOYMENT.md](DEPLOYMENT.md). Readiness and open risks: [READINESS.md](READINESS.md).

## Principles
- PostgreSQL is the only transactional store. Pinecone holds approved clinic information only (hours, policies, FAQs), never patient data.
- The language model can only *call read-only tools* and *propose* a booking. FastAPI services validate and execute everything; no model-generated SQL or code. A booking is created only by a human submitting a form.
- Layers: route → service → repository → model. External systems sit behind interfaces with a mock and a live adapter; the mode is `mock` unless every credential is present, and `/health/ready` reports it.
- Personal data: phone and email are Fernet-encrypted; phones are looked up by HMAC. Logs and audit records are PII-masked. Staff see masked phones.

## System
```mermaid
flowchart TD
  U[Patient / Doctor / Admin] --> WEB[Next.js on Vercel]
  WEB -->|"/api/* rewrite (same origin, first-party cookie)"| API[FastAPI on Vercel Python]
  API --> RT[Routes] --> SVC[Services] --> REPO[Repositories] --> PG[(Neon PostgreSQL)]
  SVC --> CHAT[Chat service] --> GR[Deterministic guardrails]
  CHAT --> LLM[LLM client: MockLLM or Grok via LangChain ChatXAI]
  LLM -->|tool calls| TOOLS[5 read-only tools]
  TOOLS --> SVC
  TOOLS --> RAG[Retriever] --> CH[(Pinecone, live) / in-memory index, mock]
  SVC -->|same transaction| OB[(notification_outbox)]
  GHA[GitHub Actions every 5 min] & VC[Vercel Cron daily] -->|Bearer CRON_SECRET| DRAIN["/internal/cron/notifications"]
  DRAIN --> OB
  DRAIN --> WA[WhatsApp Cloud API]
  WA -->|signed webhook| API
```

## Backend modules (`backend/app`)
| Area | Responsibility |
| --- | --- |
| `core/` | settings (fail-fast in production), JSON logging with PII masking, security headers, request-size cap on received bytes, rate limiter, crypto and JWT primitives, error envelope |
| `models/`, `repositories/` | 14 tables; queries only |
| `services/availability.py` | pure slot engine (schedules, breaks, leave, existing bookings, lead time, horizon) shared by patients and the booking transaction |
| `services/booking.py` | book / cancel / reschedule: row lock on the doctor, slots recomputed under the lock, exclusion constraint as the final guard, idempotency keys, outbox write in the same transaction |
| `services/auth.py`, `otp.py`, `staff.py`, `audit.py`, `retention.py` | staff login + rotating refresh tokens + lockout; WhatsApp OTP; dashboards; audit trail; purge of short-lived data |
| `ai/` | guardrails (emergency > injection > medical, before the model), tool registry (strict argument validation), signed booking proposals, chat loop, LLM clients |
| `rag/` | markdown chunking, embedders (hashing mock, Pinecone hosted inference), vector stores (in-memory, Pinecone), retriever |
| `notifications/` | templates, outbox writer, WhatsApp senders (mock, Cloud API), drain worker, webhook processing |
| `api/routes/` | `health`, `catalog`, `booking`, `chat`, `patient` (OTP), `auth`, `admin`, `doctor_portal`, `whatsapp` (webhook), `internal` (cron) |

## Key flows
**Guest booking.** `GET /doctors/{id}/slots` → `POST /appointments` with an `Idempotency-Key`. The service locks the doctor row, recomputes the slots, inserts the appointment and (if the patient consented) an outbox row, and commits once. Overlaps, deadlocks and serialization failures all surface as `409 slot_unavailable`.

**Chat.** Input guardrails (emergency, injection, medical) run before any model call. Phone numbers and emails are masked in the text. The model may call `list_specializations`, `find_doctors`, `get_available_slots`, `clinic_info` (RAG) and `propose_booking`. The last returns a 10-minute signed proposal that the model never sees; the UI posts it with the patient's own details to `/chat/confirm`, which uses the normal booking service. Output guardrails block leaked prompts, links and dosage-like text.

**Notifications.** Outbox rows are claimed with `FOR UPDATE SKIP LOCKED`, sent, logged per attempt, retried with backoff (1 m → 6 h, six attempts) and marked `DEAD` on permanent errors. Delivery is at-least-once. In production the drain refuses to run with the mock sender. Delivery receipts and `STOP` replies arrive on the signed webhook.

**Patient self-service.** WhatsApp OTP → 15-minute patient token → list / cancel / reschedule *own* appointments (ownership via phone hash; "not yours" = 404).

**Staff.** Email + password → 15-minute access token (memory only) + HttpOnly refresh cookie (rotating, theft-detecting). Every request re-checks the user in the database. Admin and doctor APIs are separate; doctors are scoped to their own data.

## Decisions and deviations from the original plan
- **No separate worker host.** The outbox lives in PostgreSQL and a secret-protected endpoint drains it; the trigger is Vercel Cron (daily on Hobby) plus a GitHub Actions schedule.
- **LangChain is used as the model client** (`langchain-xai` `ChatXAI`), not as an agent framework: the tool loop, argument validation and guardrails are our own code, which keeps the safety properties testable.
- **Five tools, not nine.** Only what the product needs: no cancel/reschedule tool exists for the model.
- **Embeddings:** hashing embedder in mock mode; Pinecone-hosted `llama-text-embed-v2` (1024 dimensions, asymmetric passage/query input types) when `PINECONE_API_KEY` is set. The ingest CLI is the only writer to Pinecone.
- **Same-origin proxy** (`/api` rewrite) is the recommended topology so the refresh cookie is first-party. A cross-site mode (`SameSite=None`) is supported but depends on third-party cookies.
- **Two independent projects** (`backend/`, `frontend/`), no npm workspace.
- **Enums as constrained strings**, soft deletes, UTC storage with Asia/Kolkata presentation.

## Not in scope of this build
Schedule editing, password change/reset, MFA, chat feedback endpoint, patient data export/erasure tooling, error tracking/alerting, multi-region. See [READINESS.md](READINESS.md).
