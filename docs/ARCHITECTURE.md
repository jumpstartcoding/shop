# Architecture

This document records the decisions made before writing code: architecture, schema, folder layout, auth, payments, signatures, deployment, backups, cost, and the build phases. It is the reference the code is checked against. If the code and this document disagree, one of them is a bug.

Guiding question for every feature: **does this make running a one-person shop easier?**

---

## 1. Shape of the system

One frontend, one backend, one database, one bucket.

```
                        ┌──────────────────────────── AWS ─────────────────────────────┐
 Phone / laptop  ──►  CloudFront (HTTPS, one domain)                                   │
                        │   /*        ──► S3 bucket: built React app (public site +   │
                        │                 admin dashboard + customer link pages)      │
                        │   /api/*    ──► Lambda Function URL ──► FastAPI (Mangum)    │
                        │                                           │                 │
                        │                     S3 bucket: photos, signed PDFs ◄──┤     │
                        │                     SES: transactional email ◄────────┤     │
                        │                     EventBridge Scheduler (nightly) ──►│     │
                        └───────────────────────────────────────────┼─────────────────┘
                                                                    │
                                         Neon Postgres (serverless) ◄┘
                                         Stripe (hosted Checkout + webhooks)
```

Why each piece:

| Piece | Choice | Why |
|---|---|---|
| Frontend | React + TypeScript + Vite + Tailwind, static build on S3 | No server to run. One app with three areas: public site, `/admin`, and customer link pages (`/e/:token`, `/i/:token`, …). |
| API | FastAPI in a **container-image Lambda**, behind a Lambda Function URL | Pays per request; free tier covers a one-person shop. Container image because WeasyPrint (PDFs) needs system libraries (Pango/Cairo). |
| Edge | CloudFront serving both `/` and `/api/*` | Same origin for the SPA and the API, so cookies are first-party, no CORS, one TLS certificate. |
| Database | **Neon Postgres** (free plan to start) | RDS is the only AWS-native Postgres and it carries a fixed monthly instance cost; Neon scales to zero and charges for use. Postgres either way, so moving later is a `pg_dump`/`pg_restore`. |
| Files | S3, uploads via presigned URLs, images compressed in the browser before upload | Lambda never proxies large uploads; photos stay small. |
| Email | Amazon SES | Same AWS account, pay per message. |
| Payments | Stripe Checkout (hosted) + webhooks | Card data never touches this system. Apple Pay / Google Pay come with Checkout. |
| PDFs | WeasyPrint (HTML/CSS → PDF) on the server, Barlow fonts bundled (SIL OFL) | Real print layout, consistent branding, no browser screenshots. The Lambda image installs Pango/HarfBuzz. |
| Scheduled jobs | EventBridge Scheduler → same Lambda with a task payload | Overdue invoices, maintenance reminders. No queues, no workers. |
| Secrets | SSM Parameter Store (standard tier) | Free, unlike Secrets Manager per-secret pricing. |
| IaC | AWS SAM template | One file describes the Lambda, bucket, CloudFront, scheduler. |

Deliberately absent: Redis, queues, Kubernetes, Elasticsearch, a separate auth service, microservices. Search uses Postgres (`pg_trgm` indexes). Rate limiting uses Postgres. Background work runs inside the request when it's quick (send one email) or on the nightly schedule.

### Lambda-specific notes
- **DB connections:** SQLAlchemy uses `NullPool` on Lambda and connects through Neon's pooled (PgBouncer) endpoint, so cold starts don't exhaust connections.
- **Cold starts:** expect ~1–2 s on the first request after idle. The admin app shows a loading state; nothing customer-facing depends on sub-second first loads. Provisioned concurrency would remove this but costs money every month, so it is off.
- **Abuse/cost guard:** reserved concurrency is capped (default 10) so a traffic spike can't run up a bill.
- **Origin protection:** the Function URL is public by AWS design, so CloudFront injects a secret header and the app rejects requests without it. (CloudFront OAC for Lambda URLs requires clients to hash POST bodies, which breaks ordinary browser forms and Stripe webhooks, so the header approach is used instead.)
- **Operational tasks** run by invoking the same function with a payload: `{"task": "migrate"}`, `{"task": "create_admin", ...}`, `{"task": "nightly"}`.

---

## 2. Data model

All money is stored as **integer cents**. Quantities and hours are `NUMERIC(10,2)`. Tax rates are `NUMERIC(7,4)` percent (e.g. `8.8750`). Every table has `id` (bigint identity), `created_at`, `updated_at`. Soft deletion is an `archived_at` timestamp on records a shop would want to restore (customers, vehicles, parts, vendors, services); financial documents are never deleted, only voided.

### Phase 1 tables
| Table | Purpose | Key constraints |
|---|---|---|
| `users` | Admin login. `role` column (`owner` now; `tech`, `office` later). | unique lower(email) |
| `sessions` | Server-side sessions; stores SHA-256 of the cookie token, never the token. | FK users, index on token_hash |
| `businesses` | One row: shop profile, tax rate, labor rate, prefixes, authorization language, hours (JSON). Named for future multi-location. | single-row check |
| `customers` | People. `internal_notes` is a separate column from anything customer-facing. | trigram indexes on name/phone/email |
| `vehicles` | Belongs to a customer. | unique VIN when present; index on plate |
| `appointments` | Requested/confirmed visits; optional link to a work order. | status check |
| `work_orders` | The repair order. Concern, internal notes, customer-facing notes, status (board columns), QC checklist (JSON), mileage in/out. | unique number, status check |
| `work_order_items` | Labor / part / fee / discount lines. | kind check, qty > 0 |
| `estimates` | Quote with expiry, version, sent/viewed/approved/declined timestamps. Optional link to a work order. | unique number |
| `estimate_items` | Same line shape as work order items. | |
| `invoices` | Snapshot of what's billed: totals, tax rate used, amount paid, status. | unique number |
| `invoice_items` | Same line shape; **copied**, not referenced, so later edits to a work order never change an issued invoice. | |
| `payments` | Manual (cash/check/card/other) now; Stripe in Phase 3. `status` allows `void`. | amount > 0, unique provider_ref |
| `document_counters` | `(kind, year) → last value` for gap-free sequential numbers (`INV-2026-0001`). Row-locked increment. | PK (kind, year) |
| `services` | Public website service catalog, editable in admin. | |
| `audit_logs` | Who did what to which record, when, with a small JSON diff. Append-only. | index (entity, entity_id) |

### Added in later phases
| Table | Phase | Purpose |
|---|---|---|
| `access_tokens` | 2 | Tokenized customer links. Stores SHA-256 of a 256-bit random token, scope (`estimate:view`, `invoice:pay`, …), target id, expiry, revoked flag. |
| `document_versions` | 2 | Immutable snapshot of a document as sent/signed: JSON content, rendered PDF S3 key, SHA-256 of the PDF. |
| `authorizations` | 2 | Signature/approval records (covers spec's `estimate_approvals` and §56): signer name/contact, decision, method (drawn, typed, link decline, or recorded by the shop from phone/in person), statement text shown, signature image key or typed name, IP, user agent, timestamp, `document_version_id`, `signed_version_id`, status (valid/superseded). |
| `inquiries` | 2 | Website contact messages and customers' questions about a document. |
| `email_templates`, `email_log` | 2 | Shop edits to built-in templates (absent row = built-in wording); every send attempt with status sent/failed/skipped. |
| `stripe_events` | 3 | Processed webhook event IDs, for idempotency. |
| `inspections`, `inspection_items` | 4 | Digital inspection (Good / Monitor / Needs Attention / Urgent) with recommended repair and estimated cost. |
| `photos` | 4 | S3 key + polymorphic owner (`work_order`, `inspection_item`, `vehicle`, …). |
| `service_records` | 4 | Written when a work order completes, plus manual entries for history done elsewhere. |
| `parts`, `vendors` | 5 | Simple catalog and vendor list; optional stock decrement. |
| `expenses` | 5 | Expense log with receipt photo. |
| `maintenance_reminders` | 5 | Due date and/or mileage per vehicle; nightly job emails due ones. |

Notes on the spec's suggested list: `notifications` is **computed** from live data (new requests, estimates awaiting approval, overdue invoices, reminders due) rather than stored, so it can't drift out of sync. `documents` is covered by `document_versions`. `estimate_approvals` is generalized into `authorizations` so estimates, additional-repair approvals, inspection reports, and terms all use one signing flow.

### Line items and the pricing engine
Every line has: `kind` (labor, part, fee, discount), `description`, `quantity` (hours for labor), `unit_price_cents`, `unit_cost_cents` (parts, internal only), `taxable`, optional part number / vendor / warranty fields.

```
line_total     = round_half_up(quantity × unit_price)
subtotal       = labor + parts
fees           = Σ fee lines
discounts      = Σ discount lines
taxable_base   = Σ taxable labor/part/fee − Σ taxable discounts   (floored at 0)
tax            = round_half_up(taxable_base × rate / 100)
total          = subtotal + fees − discounts + tax
```
Rounding happens once per line and once for tax, in a single pure function (`app/core/pricing.py`) that every document uses. Part markup is a convenience: if a part line is given cost and markup but no price, price = cost × (1 + markup%). Which line kinds are taxable by default is a shop setting; each line can override. The app makes no claim about what is taxable in any state; the shop configures it and the UI carries a not-tax-advice notice.

---

## 3. Folder structure

```
mechanic-shop/
├── README.md                 setup, local dev, cost estimate, feature list
├── docs/
│   ├── ARCHITECTURE.md       this file
│   ├── DEPLOYMENT.md         (Phase 6) AWS + Neon + Stripe + SES setup
│   ├── SECURITY.md           (Phase 6) checklist and threat notes
│   └── BACKUPS.md            (Phase 6) frequency, retention, restore drill
├── backend/
│   ├── pyproject.toml        uv-managed
│   ├── alembic.ini
│   ├── migrations/           Alembic revisions
│   ├── app/
│   │   ├── main.py           FastAPI app factory, middleware, routers
│   │   ├── lambda_handler.py Mangum adapter + task dispatch
│   │   ├── config.py         settings from env
│   │   ├── db.py             engine/session (NullPool on Lambda)
│   │   ├── core/             security, pricing, numbering, audit, errors, deps
│   │   ├── models/           SQLAlchemy models
│   │   ├── schemas/          Pydantic request/response models
│   │   ├── routers/          one module per resource
│   │   └── services/         workflows that span tables (convert estimate, invoice from WO, record payment)
│   └── tests/
├── frontend/                 (Phase 1b) React app
├── infra/
│   └── template.yaml         (Phase 6) AWS SAM
└── .github/workflows/        CI tests; nightly DB backup
```

---

## 4. Authentication and authorization

- **One owner account** created by a CLI/Lambda task, never by a public signup route.
- **Passwords:** Argon2id (`argon2-cffi`), minimum 12 characters.
- **Sessions:** 256-bit random token in an `HttpOnly; Secure; SameSite=Strict` cookie. Only its SHA-256 is stored. Idle timeout 7 days, absolute 30 days, revoked on logout and on password change.
- **CSRF:** double-submit token. A readable `csrf` cookie is mirrored into an `X-CSRF-Token` header on every state-changing request; the server compares in constant time. SameSite=Strict is the first layer, this is the second.
- **Login throttling:** per-account failure counter with a temporary lock (10 failures → 15 minutes), stored in Postgres. No Redis.
- **Authorization:** every admin route depends on `require_user`; roles are checked through one `require_role(...)` dependency so adding employees later is a data change, not a rewrite.
- **Customer access:** no customer accounts in V1. Customers get **scoped, expiring, revocable links** (Phase 2). A link grants exactly one action on exactly one document. The token is never stored in plaintext. Internal notes and part costs are excluded from every customer-facing serializer by construction (separate Pydantic schemas), not by filtering.

---

## 5. Payment architecture (Phase 3)

1. Customer opens `/i/:token` → sees invoice, balance, and a "Pay" button with the amount prefilled (editable down for a partial payment, never above the balance, minimum $1).
2. API creates a **Stripe Checkout Session** for that amount, with `invoice_id` and `access_token_id` in metadata, and a per-attempt idempotency key.
3. Customer pays on Stripe's page (cards, Apple Pay, Google Pay).
4. Stripe calls `POST /api/webhooks/stripe`. The handler verifies the signature against the raw body, records the event ID in `stripe_events` (unique, so replays are no-ops), then inserts the payment and recomputes the invoice balance **in one transaction with the invoice row locked**.
5. The success redirect page never marks anything paid; it only polls the invoice. The webhook is the single source of truth.
6. Refunds (`charge.refunded`) create a negative adjustment and an audit entry.

Stored: amount, method, Stripe payment intent ID, status, timestamps. Never stored: card numbers, CVC, or anything else Stripe doesn't return as safe metadata.

---

## 6. Signatures and document integrity (Phase 2, spec §56)

1. Mechanic clicks "Send for signature" on an estimate, additional-repair request, inspection report, work order, or terms document.
2. Server renders the PDF, stores it in S3, and writes a `document_versions` row with the JSON snapshot and the PDF's SHA-256. The source document is now **locked**: edits are refused until the mechanic explicitly creates a new version.
3. Customer opens the link, reviews the rendered document, ticks the authorization checkbox showing the shop's configured statement, then draws a signature (canvas, finger or mouse) or types their name if the shop allows typed signatures.
4. Server stores an `authorizations` row (signer name, contact, decision, statement text as shown, signature PNG key or typed name, IP and user agent, timestamp, version id), renders the **signed PDF** (original content + signature block + document ID + version + content hash), stores it, and writes an audit entry.
5. Any later material change creates version N+1, marks the prior authorization `superseded`, and requires a new signature. A signed version is never modified.

The app records a strong electronic authorization trail. It does not claim any particular legal enforceability; the README and settings page say the shop is responsible for authorization language appropriate to its jurisdiction.

---

## 7. Deployment (Phase 6 docs; template built alongside)

- `sam build && sam deploy` creates: ECR image, Lambda (arm64, 1024 MB, 30 s timeout, reserved concurrency 10), Function URL, private S3 buckets (site + files), CloudFront distribution with two behaviors, EventBridge nightly schedule, IAM role scoped to its own bucket and SES identity.
- Frontend: `npm run build` → `aws s3 sync` → CloudFront invalidation (GitHub Actions).
- Migrations: `aws lambda invoke --payload '{"task":"migrate"}'` as a deploy step.
- DNS: Route 53 hosted zone (or keep the registrar's DNS and add CNAMEs to skip the hosted-zone fee). ACM certificate in us-east-1 for CloudFront.
- SES starts in sandbox mode; production access must be requested from AWS before customers can receive email (documented step).

---

## 8. Backups

| Layer | What | Frequency | Retention |
|---|---|---|---|
| Neon restore window | Point-in-time restore of the branch | Continuous | 6 hours on the free plan (7 days on paid Launch) |
| Nightly logical dump | `pg_dump --format=custom` from GitHub Actions → S3 (`backups/`) | Daily | 35 days via S3 lifecycle rule, plus the 1st of each month kept 12 months |
| Files | S3 versioning on the files bucket | On write | Noncurrent versions expire after 30 days |
| Export | CSV export from the app | On demand | Shop's own copy |

The 6-hour free-tier window is too short to be the only protection, which is why the nightly dump is not optional. The restore procedure is documented and should be rehearsed once into a scratch Neon branch.

---

## 9. Production cost estimate

Assumes one shop: a few hundred customers, ~100 work orders/month, a few thousand page views, ~300 emails/month, a few GB of photos. Prices checked October 2026; confirm before launch.

| Item | Expected monthly | Notes |
|---|---|---|
| Lambda + Function URL | $0 | Well inside the always-free tier. |
| CloudFront | $0 | Inside the always-free tier for this traffic. |
| S3 (site + photos + backups) | $0.10–$0.50 | A few GB at standard rates; photos compressed client-side. |
| ECR image storage | ~$0.05 | ~300–500 MB image. |
| Neon Postgres | $0 | Free plan: 1 GB per project and 100 CU-hours/month, scale to zero. Moves to usage-based Launch if outgrown. |
| SES email | ~$0.03 | $0.10 per 1,000 emails. |
| EventBridge, SSM | $0 | Free tiers. |
| Route 53 hosted zone | $0.50 | Optional if the registrar's DNS is used. |
| Backups (GitHub Actions + S3) | ~$0.01 | Free Actions minutes; tiny dump files. |
| **Infrastructure subtotal** | **≈ $0.60–$1.10/month** | |
| Domain | ~$1–1.25/month | ~$12–15/year, paid annually. |
| **Stripe** | 2.9% + 30¢ per online card payment | On $10,000/month of online card payments that is roughly $290 + 30¢ × number of payments. Non-US cards add 1.5%. Cash/check recorded manually cost nothing. Disputes carry a $15 fee. |

Payment processing is, by a wide margin, the largest cost of operating this system. Infrastructure stays under the $10 target with room to spare; the first thing likely to cost money is outgrowing Neon's free plan.

---

## 10. Build phases

Each phase ships working, tested functionality. Nothing is stubbed to look finished.

| Phase | Scope |
|---|---|
| **1a** Backend core (done) | Config, DB, migrations, auth, audit log, pricing engine, numbering; customers, vehicles, appointments, work orders, estimates, invoices, manual payments, settings, services catalog, dashboard summary, global search; tests on real Postgres. |
| **1b** Admin UI (done) | Mobile-first React admin: dashboard, search, customers, vehicles, calendar, work order editor + status board, estimates, invoices, record payment, settings. |
| **2** Customer links, PDFs, email, signatures (done) | Access tokens, customer estimate/invoice pages, approve/decline/question, additional-repair approvals, signature capture, document versions and locking, WeasyPrint PDFs, SES email + editable templates, public website + booking form. |
| **3** Online payments | Stripe Checkout, webhook handling (heavily tested), receipts, refunds. |
| **4** Inspections and photos | Digital inspection, presigned uploads with client-side compression, inspection report PDF, service history, QC checklist enforcement. |
| **5** Shop admin | Parts, vendors, expenses, maintenance reminders + nightly job, reports with date filters, CSV export, VIN decode via the free NHTSA vPIC API (optional, app works without it). |
| **6** Production hardening | SAM template, CI, backup workflow, security review against §52, DEPLOYMENT/SECURITY/BACKUPS docs, README completion, demo data. |

## 11. Not in V1 (by design)
Multi-location, employee payroll, accounting, warehouse inventory, CRM campaigns, fleet management, SSO, AI diagnostics, supplier APIs, SMS (architecture leaves room: reminders and templates are channel-agnostic), customer login accounts (links cover V1).
