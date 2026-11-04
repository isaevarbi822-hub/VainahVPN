# RollyPay adapter for VainahVPN Python/Render

**Status:** code preparation only. This directory is **not deployed**. The current `VainahVPN` repository has no Python server; merge this into the source actually deployed by Render. No live payments or H1Cloud entitlements are enabled here.

## What it supports

- Read-only `GET /api/v1/balance` with `X-API-Key` + unique `X-Nonce` to test credentials (balance is not exposed to website users).
- Raw-body HMAC-SHA256 validation over `X-Timestamp + "." + body`, 5-minute freshness, constant-time signature comparison.
- Basic webhook payload validation and durable, idempotent PostgreSQL event recording (including refunds and chargebacks).
- An optional FastAPI router: `/api/health/rollypay`, `/api/health/rollypay-webhook`, and `POST /webhooks/rollypay`.
- A client method that creates **sandbox-only** (`test: true`) payments and a helper to compare paid provider records with an existing order.

## Server configuration

Install dependencies for the optional router:

```bash
pip install fastapi 'psycopg[binary]'
```

Import and mount from an existing FastAPI application:

```python
from payments.fastapi_routes import router as rollypay_router
app.include_router(rollypay_router)
```

Execute `sql/rollypay_events.sql` in the connected PostgreSQL database before deployment.

Add to **Render → your web service → Environment**, not GitHub:

```dotenv
ROLLYPAY_API_KEY=<actual API key supplied by RollyPay>
ROLLYPAY_SIGNING_SECRET=<actual signing_secret supplied by RollyPay>
DATABASE_URL=<existing Postgres connection string>
```

Do not invent a signing secret: it must match **the secret assigned to the terminal by RollyPay**. In the RollyPay terminal set `callback_url` to your deployed route, e.g. `https://vainahvpn-python-preview.onrender.com/webhooks/rollypay`, **only after that route responds and the DB migration is applied**. Do not reuse the old Netlify webhook URL.

## Gate to production

This module **does not** automatically issue VPN entitlements. To enable later:

1. Authenticate customer, create order from the fixed server-side plan catalog, and persist it before requesting checkout.
2. Obtain RollyPay `payment_id` and `pay_url` server-side; never expose `ROLLYPAY_API_KEY` to browsers or apps.
3. For a signed real `payment.paid`, independently call `GET /api/v1/payments/{payment_id}`; compare its payment ID, order ID, exact amount, currency, status, and sandbox flag against the existing order.
4. Claim order fulfillment atomically in PostgreSQL so replayed webhooks cannot extend it twice; then provision H1Cloud and mark delivery separately, with bounded retries.
5. Handle late `refunded`/`chargeback`, monitor event backlog, and only then enable production checkout after sandbox end-to-end tests.

Until the fulfillment worker is built, webhook events are stored but left unprocessed; `processed_at` remains NULL. No new paid purchases should be offered before the whole sequence works. The status check that shows `verified_delivery: false` is deliberate; a secret configured in Render does not prove the webhook arrived.

Run standard-library tests from the folder containing `payments/`:

```bash
python -m unittest discover -s tests -v
```

API documentation: https://docs.rollypay.io/api/authentication/ · https://docs.rollypay.io/api/callbacks/ · https://docs.rollypay.io/api/balance-rate/ · https://docs.rollypay.io/api/payments/
