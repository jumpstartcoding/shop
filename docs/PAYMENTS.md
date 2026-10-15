# Online payments (Stripe)

Customers pay invoices on Stripe's hosted Checkout page: cards, plus Apple Pay and Google Pay on supported devices. Card numbers never touch this app. The app stores only Stripe's payment intent and checkout session ids, so refunds can be matched and you can look a payment up in the Stripe dashboard.

Without Stripe keys the app works normally; invoice links just tell customers to call or pay at the shop.

## How a payment flows

1. You send an invoice link (Invoices, **Send to customer**).
2. The customer opens it, chooses the full balance or a partial amount (minimum $1.00), and taps **Pay with card**.
3. The app creates a Stripe Checkout Session for that amount and sends them to Stripe.
4. When the payment succeeds, Stripe sends a **signed webhook**. Only the webhook records the payment. The page the customer returns to just waits for it, then shows "Payment received" with a receipt.
5. The invoice's paid amount and status update, a PDF receipt is emailed to the customer, and the Today screen shows the payment.

Safeguards:
- Every webhook signature is verified (HMAC-SHA256, 5-minute tolerance). Unsigned, tampered, or replayed-late requests are rejected.
- Each Stripe event id is stored in the same database transaction as the payment, with the invoice row locked. Retries, duplicates, and simultaneous deliveries record a payment exactly once.
- If processing fails, the whole transaction rolls back and Stripe retries automatically.
- If two payments overlap (two tabs) or a payment arrives for a voided invoice, the money is recorded (it was really taken) and the invoice is flagged **overpaid** on the Today screen with a prompt to refund the difference. The shop is emailed.
- A double tap on **Pay** within a minute reuses the same Stripe session (idempotency key).

## Refunds

From the invoice, tap **Refund** on a payment and enter an amount (partial or full) and a reason.
- **Online payments** are refunded to the customer's card through Stripe. Stripe usually returns the money in 5 to 10 business days and does not refund its processing fee. If Stripe refuses, nothing in the app changes and you're told no money was moved.
- **Cash, check, or card-terminal payments** are recorded as refunded; hand the money back yourself.
- Refunds made directly in the Stripe dashboard are picked up by the `charge.refunded` webhook and applied to the invoice automatically.

Card disputes (`charge.dispute.created`) are recorded on the invoice and emailed to the shop. Respond to them in the Stripe dashboard; Stripe charges a dispute fee.

## Setup

### 1. Create a Stripe account
Sign up at stripe.com and complete business verification. Stay in **test mode** until everything works.

### 2. Add the keys
In the Stripe dashboard, open **Developers → API keys** and copy the secret key (`sk_test_...` in test mode). A restricted key also works if it has write access to Checkout Sessions and Refunds.

Set in the backend environment (SSM Parameter Store in production, `backend/.env` locally):
```
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...      # from step 3
```

### 3. Register the webhook
In **Developers → Webhooks**, add an endpoint:
- URL: `https://YOUR-DOMAIN/api/webhooks/stripe`
- Events:
  - `checkout.session.completed`
  - `checkout.session.async_payment_succeeded`
  - `checkout.session.async_payment_failed`
  - `charge.refunded`
  - `charge.dispute.created`

Copy the endpoint's **signing secret** into `STRIPE_WEBHOOK_SECRET`.

### 4. Turn it on
In the app, **Settings → Online payments** shows whether Stripe is connected and in which mode. Leave **Let customers pay invoices online** checked.

### 5. Test, then go live
Pay a test invoice with card `4242 4242 4242 4242`, any future expiry, any CVC. Check that the invoice updates, the receipt email arrives, and a refund works. Then switch the dashboard to live mode, create live keys and a live webhook endpoint, and replace both values. Settings will show **live mode**.

## Local development

Install the Stripe CLI, then forward webhooks to your laptop:
```bash
stripe login
stripe listen --forward-to localhost:8000/api/webhooks/stripe
```
The CLI prints a `whsec_...` secret; put it in `backend/.env` as `STRIPE_WEBHOOK_SECRET` and restart the API.

## Costs

Stripe's standard US pricing is **2.9% + 30¢ per successful card payment**, deducted before payout. Cards issued outside the US add 1.5%. Disputes cost $15 each. There is no monthly fee. Cash and checks recorded in the app cost nothing.

Some states restrict or regulate card surcharges, so the app does not add a fee to the customer's total. If you want to pass fees on, check your state's rules first.
