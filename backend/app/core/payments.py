"""The payment provider boundary. Everything that talks to Stripe goes through here.

Card details never touch this system: customers pay on Stripe's hosted Checkout page, and
Stripe tells us what happened through signed webhooks. The only Stripe identifiers stored are
the payment intent id (to match refunds) and the checkout session id (for support lookups).
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.config import get_settings
from app.core.errors import AppError

# Written into Checkout metadata so events from other tools on the same Stripe account
# (an online store, a booking app) are recognized and ignored.
METADATA_SOURCE = "shop-app"


class PaymentsUnavailable(AppError):
    status_code = 409
    code = "payments_unavailable"


class PaymentProviderError(AppError):
    status_code = 502
    code = "payment_provider_error"


class BadWebhook(AppError):
    status_code = 400
    code = "bad_webhook"


@dataclass
class CheckoutSession:
    id: str
    url: str


class Gateway(Protocol):
    def create_checkout(
        self,
        *,
        amount_cents: int,
        currency: str,
        description: str,
        customer_email: str | None,
        metadata: dict[str, str],
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> CheckoutSession: ...

    def refund(
        self, *, payment_intent: str, amount_cents: int, idempotency_key: str, reason_note: str
    ) -> str: ...


class StripeGateway:
    def __init__(self, api_key: str):
        import stripe

        self._stripe = stripe
        self.client = stripe.StripeClient(api_key, max_network_retries=2)

    def create_checkout(
        self,
        *,
        amount_cents,
        currency,
        description,
        customer_email,
        metadata,
        success_url,
        cancel_url,
        idempotency_key,
    ) -> CheckoutSession:
        params = {
            "mode": "payment",
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": currency,
                        "unit_amount": amount_cents,
                        "product_data": {"name": description},
                    },
                }
            ],
            "metadata": metadata,
            "payment_intent_data": {"metadata": metadata, "description": description},
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        if customer_email:
            params["customer_email"] = customer_email
        try:
            s = self.client.checkout.sessions.create(
                params=params, options={"idempotency_key": idempotency_key}
            )
        except self._stripe.StripeError as exc:
            raise PaymentProviderError(
                "The payment page couldn't be opened. No charge was made. Please try again."
            ) from exc
        return CheckoutSession(id=s.id, url=s.url)

    def refund(self, *, payment_intent, amount_cents, idempotency_key, reason_note) -> str:
        try:
            r = self.client.refunds.create(
                params={
                    "payment_intent": payment_intent,
                    "amount": amount_cents,
                    "metadata": {"source": METADATA_SOURCE, "note": reason_note[:400]},
                },
                options={"idempotency_key": idempotency_key},
            )
        except self._stripe.StripeError as exc:
            raise PaymentProviderError(
                "The refund could not be processed. No money was moved. "
                + (
                    getattr(exc, "user_message", None)
                    or "Try again, or refund it in your Stripe dashboard."
                )
            ) from exc
        return r.id


_override: Gateway | None = None


def set_gateway(gateway: Gateway | None) -> None:
    """Tests swap in a fake gateway here."""
    global _override
    _override = gateway
    _stripe_gateway.cache_clear()


@lru_cache
def _stripe_gateway() -> StripeGateway:
    return StripeGateway(get_settings().stripe_secret_key.get_secret_value())


def get_gateway() -> Gateway:
    if _override is not None:
        return _override
    if not get_settings().stripe_configured:
        raise PaymentsUnavailable("Online payments aren't set up for this shop.")
    return _stripe_gateway()


def verify_webhook(payload: bytes, signature_header: str | None) -> dict:
    """Check Stripe's signature (HMAC-SHA256 over timestamp + raw body, 5-minute tolerance)
    and return the parsed event. Anything unsigned or stale is rejected."""
    import stripe

    secret = get_settings().stripe_webhook_secret.get_secret_value()
    if not secret:
        raise BadWebhook("Webhook secret not configured.")
    if not signature_header:
        raise BadWebhook("Missing signature.")
    try:
        stripe.WebhookSignature.verify_header(payload, signature_header, secret, tolerance=300)
    except stripe.SignatureVerificationError as exc:
        raise BadWebhook("Invalid signature.") from exc
    try:
        event = json.loads(payload)
    except ValueError as exc:
        raise BadWebhook("Invalid payload.") from exc
    if not isinstance(event, dict) or "id" not in event or "type" not in event:
        raise BadWebhook("Invalid event.")
    return event
