# Shop

Website and shop-management system for a one-person auto repair shop: customers, vehicles, appointments, work orders, estimates, invoices, payments, and a public website, built to run from a phone in the bay for about a dollar a month in infrastructure.

> **Placeholder shop details.** The demo data uses a fictional shop, "Ridgeline Auto Repair", with a 555-01xx phone number, a sample address, an 8% tax rate on parts, and a $120/h labor rate. Replace all of it in Settings before going live.

## Status

Built in phases; each phase ships working, tested functionality. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full plan and the reasoning behind every choice.

| Phase | Scope | State |
|---|---|---|
| 1a | Backend core: auth, customers, vehicles, appointments, work orders, estimates, invoices, manual payments, settings, services catalog, dashboard, search, audit log | **Done** (54 tests passing) |
| 1b | Mobile-first admin UI (React) | Next |
| 2 | Customer links, PDFs, email, digital signatures, public website and booking | Planned |
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

What it does **not** do yet: send email, generate PDFs, take signatures, take card payments online, or show a website. Those endpoints don't exist rather than existing as stubs. "Mark sent" records that you handed or sent a document yourself.

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

Then open http://localhost:8000/api/docs for the interactive API documentation. Demo sign-in: `demo@example.com` / `demo-password-123` (created only by `seed-demo`, which refuses to run in production).

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
