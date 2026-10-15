# Shop

Website and shop-management system for a one-person auto repair shop: customers, vehicles, appointments, work orders, estimates, invoices, payments, and a public website, built to run from a phone in the bay for about a dollar a month in infrastructure.

> **Placeholder shop details.** The demo data uses a fictional shop, "Ridgeline Auto Repair", with a 555-01xx phone number, a sample address, an 8% tax rate on parts, and a $120/h labor rate. Replace all of it in Settings before going live.

## Status

Built in phases; each phase ships working, tested functionality. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full plan and the reasoning behind every choice.

| Phase | Scope | State |
|---|---|---|
| 1a | Backend core: auth, customers, vehicles, appointments, work orders, estimates, invoices, manual payments, settings, services catalog, dashboard, search, audit log | **Done** (54 tests passing) |
| 1b | Mobile-first admin UI (React) | **Done** |
| 2 | Customer links, PDFs, email, digital signatures, public website and booking | **Done** (81 backend tests) |
| 3 | Stripe online payments, receipts, refunds | Planned |
| 4 | Inspections, photos, service history | Planned |
| 5 | Parts, vendors, expenses, reminders, reports, CSV export, VIN decode | Planned |
| 6 | AWS deployment template, backups, security review, final docs | Planned |

### What Phase 1a does today
- **Sign-in:** one owner account, Argon2id passwords, server-side sessions in HttpOnly cookies, CSRF tokens, temporary lockout after repeated failures.
- **Customers and vehicles:** add a customer and their vehicle in one step; search by name, phone (any format), email, VIN, plate, or make/model; archive and restore; VIN normalization and duplicate detection; full per-customer and per-vehicle history.
- **Appointments:** calendar feed by date range, reschedule by changing times, statuses from requested to no-show.
- **Work orders:** sequential numbers (`WO-2026-0001`), labor/part/fee/discount lines, default labor rate, part price from cost + markup, per-line taxability, status board columns, completion checklist (override is allowed but audited), mileage tracking.
- **Estimates:** created from scratch or from a work order; marking sent locks it; record approval/decline given in person or by phone/email/text; revising creates a new version and drops the old approval; approved estimates convert into work.
- **Invoices:** generated from a work order as a snapshot, or standalone; numbers like `INV-2026-0001`; charges freeze once money is received; void with a reason; overdue status from the due date.
- **Payments:** cash, check, card terminal, other. Overpayment is refused; voiding a payment restores the balance. Online payments arrive with Stripe in Phase 3.
- **Dashboard:** today's and upcoming appointments, requests to review, open work orders, vehicles in the shop, estimates awaiting the customer, unpaid and recently paid invoices, revenue today/week/month/year, outstanding balance, and a short list of things needing attention.
- **Audit log:** every change to customers, documents, payments, and settings, with who, when, and what changed. Internal note contents are not copied into the log.

### What Phase 1b adds
A mobile-first admin app at `/admin`, built for a phone in one hand in the bay and a laptop at the counter:

- **Today:** what needs attention, money in this week/month/year, what's owed, vehicles in the shop, today's bookings, requests, estimates out, unpaid invoices.
- **Board:** jobs grouped by stage, one tap to move to the next stage; closing out goes through the checklist.
- **Work order:** the job's "tag" (number, vehicle, customer, concern), a sideways status strip, parts and labor with shop-rate and markup defaults, estimate and invoice in one tap, notes with internal notes clearly marked.
- **Estimates and invoices:** lock state explained in plain words, record a phone/in-person approval, new versions, record cash/check/card payments with partial amounts, void with a reason.
- **Calendar:** day, week, and month views; requests without a time listed first; drag to another day on desktop; turn an online request into a customer with the form prefilled; check in straight to a work order.
- **Customers and vehicles:** one-step add with the first vehicle, call/text/email buttons, full history per customer and per vehicle.
- **Settings:** shop profile, hours, pricing and tax, document prefixes, authorization wording, website services, password.
- Global search from every screen; 48px+ touch targets; keyboard focus visible; works without horizontal scrolling at 390px wide.

### What Phase 2 adds
- **Public website** at `/`: home page with a live open/closed sign in the shop's time zone, services (editable in Settings), about, contact form, map and directions, and online booking. Reviews show only when the shop adds real ones. Booking and contact forms have a hidden spam trap and a per-connection hourly limit.
- **Customer links** (`/d/...`): estimates, repair authorizations, and invoices open on the customer's phone with no account. Each link is a 256-bit random token stored only as a hash, works for one document, expires, and stops working when a newer version is sent.
- **Signatures:** customers check the authorization statement, then draw a signature with a finger (or type their name, if the shop allows it), or decline with a reason, or ask a question. The shop can also record a phone or in-person approval; it's stored the same way and marked as recorded by the shop.
- **Document integrity:** sending locks the document as a numbered version with a SHA-256 fingerprint of its content and of its PDF. The customer sees and signs that stored version, never the live record. A signed copy (original plus signature block, signer, time, document ID, version, fingerprint) is generated and stored. Changing an approved estimate creates a new version and the old approval no longer applies; a work order that changes after signing is flagged "changed since signed". Stored PDFs are re-checked against their fingerprint before being served.
- **Additional work approvals:** "Ask approval for extra work" on a work order creates a separate approval request; when approved, its lines are added to the job.
- **PDFs** for estimates, work orders, invoices, receipts, and signed copies, rendered on the server with WeasyPrint and the bundled Barlow fonts, with the shop's logo.
- **Email** for estimates, authorizations, invoices, receipts (PDF attached), appointment confirmations, and "your car is ready". Every send is logged; a failed email never undoes the send, and the link is always shown so it can be texted instead. Templates are editable. The shop can be emailed when requests, questions, and approvals come in.
- **Today screen** shows messages from customers; the calendar turns booking requests into customers with the form prefilled.

What it does **not** do yet: take card payments online (Phase 3), inspections and photos (Phase 4).

### Electronic signatures: what this is and isn't
The signing flow is designed as a strong electronic authorization record: who signed, what exact version they saw, the statement they agreed to, when, from which IP address and device, and a fingerprint of the document. It is **not legal advice and makes no claim about enforceability in any particular state.** The shop is responsible for wording the authorization statement and terms (Settings) appropriately for its jurisdiction, and may want a local attorney to review them.

## Local development

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), and Postgres 14+ (`brew install postgresql@16` on a Mac).

```bash
cd backend
cp .env.example .env               # adjust DATABASE_URL if needed
createdb shop && createdb shop_test
uv sync
uv run python -m app.tasks migrate
uv run python -m app.tasks seed-demo       # placeholder shop + demo workflow
uv run uvicorn app.main:app --reload
```

Then open http://localhost:8000/api/docs for the interactive API documentation.

PDFs need WeasyPrint's system libraries. On a Mac: `brew install pango`. On Debian/Ubuntu: `apt install libpango-1.0-0 libpangoft2-1.0-0`. With `EMAIL_BACKEND=file`, "sent" emails appear as `.eml` files in `backend/.files/outbox`.

In a second terminal, start the admin app (Node 20+):

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173/admin, proxies /api to :8000
``` Demo sign-in: `demo@example.com` / `demo-password-123` (created only by `seed-demo`, which refuses to run in production).

To create the real owner account instead:

```bash
uv run python -m app.tasks create-admin --email you@yourshop.com --name "Your Name"
```

### Tests

```bash
cd backend
uv run pytest                      # uses TEST_DATABASE_URL; the test database is wiped
uv run ruff check app tests migrations
```

Tests run against real Postgres, not SQLite, so constraints, row locking, and numbering behave as they will in production. Covered so far: pricing and tax math, authentication and CSRF, customer/vehicle rules, appointments, the estimate → work order → invoice → payment workflow, overpayment and edit-after-payment protection, concurrent invoice numbering, settings validation, and public endpoints not leaking internal settings.

## Project layout

```
backend/
  app/
    core/        pricing engine, numbering, auth helpers, audit, errors
    models/      SQLAlchemy models
    schemas/     request/response validation
    routers/     REST endpoints under /api
    services/    workflows spanning several tables
    tasks.py     migrate, create-admin, nightly, seed-demo
  migrations/    Alembic
  tests/
frontend/
  src/
    components/  layout, line-item editor, pickers, shared UI
    pages/       one file per screen
    lib/         API client (cookies + CSRF), formatting, types
docs/ARCHITECTURE.md
```

## Production cost estimate

Assumes one shop: a few hundred customers, about 100 work orders a month, a few thousand page views, about 300 emails a month, and a few GB of photos. Prices checked October 2026; confirm before launch.

| Item | Expected monthly cost |
|---|---|
| Hosting: AWS Lambda + Function URL + CloudFront | $0 (inside always-free tiers) |
| Database: Neon Postgres free plan | $0 (1 GB storage, 100 compute-hours, scales to zero) |
| Storage: S3 for site, photos, PDFs, backups | $0.10–$0.50 |
| Container image (ECR) | ~$0.05 |
| Email: Amazon SES | ~$0.03 ($0.10 per 1,000 emails) |
| Backups: nightly dump via GitHub Actions to S3 | ~$0.01 |
| DNS: Route 53 hosted zone (optional) | $0.50 |
| **Infrastructure total** | **about $0.60–$1.10** |
| Domain | about $12–15 per year |
| **Payment processing (Stripe)** | **2.9% + 30¢ per online card payment**; non-US cards add 1.5%; $15 per dispute |

Payment processing is by far the largest cost. On $10,000 a month of online card payments, Stripe takes roughly $290 plus 30¢ per payment. Cash and checks recorded by hand cost nothing. The first infrastructure cost likely to appear is outgrowing Neon's free plan, which moves to usage-based billing.

## Tax notice

The app applies tax exactly as configured in Settings (rate, and whether labor, parts, and fees are taxable by default, overridable per line). It does not know any state's rules and is not tax or accounting advice.
