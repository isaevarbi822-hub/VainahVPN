# Vainah VPN — private live RollyPay pilot (operator runbook)

This runbook is for the **authorized adult merchant/account operator** and
the developer responsible for H1Cloud. This mode exists so that a *single*
real paid transaction can be independently verified before public charging is
enabled. No test/sandbox payment counts as live evidence.

## Current behavior

- Public `POST /api/shop/checkout` stays **disabled** until
  `VAINAH_LIVE_PAID_E2E_VERIFIED=verified`, the normal live approval flags,
  and all infrastructure checks pass.
- The operator-only route
  `POST /api/shop/operator/live-pilot/checkout` uses the same validated hosted
  RollyPay checkout and signed webhook as a normal live sale, but is disabled
  by default and does *not* require a completed E2E before the pilot.
- A pilot is **a real payment and can charge money**. It is not sandbox mode.
- The pilot requires both an operator token and a distinct second pilot token,
  a server-verified email session with exactly the allowed mailbox, a
  same-origin request, and a UUID v4 idempotency key.
- Only the cheapest 30-day plan (`plan = "30"`) is allowed, and a unique
  PostgreSQL index permits only **one pilot order across all workers**, ever.
  New UUIDs cannot create additional pilot invoices, even if a network call
  to RollyPay timed out. Never drop or reset the index to retry an uncertain
  charge.
- The real-money webhook can process a pilot event while public sales are
  closed **only** if its HMAC signature is valid and the order belongs to the
  persistently recorded pilot. No data from the callback may designate a
  different order as a pilot.
- After a pilot invoice exists, disabling `VAINAH_LIVE_PILOT_ENABLED`
  stops **new checkout** but **does not stop signed callbacks** for that
  immutable order. The existing callback still needs merchant, H1 contract,
  and fulfillment attestations plus working infrastructure. Revoking those
  approvals stops processing and may require manual payment reconciliation.
- H1 writes still use single-claim safe fulfillment. No ambiguous H1 write is
  retried automatically. The receipt is sent only after the paid H1 link was
  durably recorded and is safe to retry without creating another VPN.

## Authorizations and opt-in (not yet enabled)

Before an adult merchant intentionally opts in, independently verify:

1. The RollyPay merchant is approved to accept real payments for the intended
   product, with correct legal entity/operator, settlement and refund policies.
2. The H1Cloud **production** write contract is authorized and that write
   preflight + postcheck work through verified HTTPS. Successful sandbox
   auto-issuance is useful but does not verify the live contract.
3. A verified login account and Resend email delivery are working; current
   H1 TLS, RollyPay API/signing secrets and PostgreSQL pass readiness checks.
4. All secrets are securely stored in Render, not committed or shared in
   screenshots/chat. Rotate any exposed operator token.

The following independent environment opt-ins are required for the pilot
and are **not set by this code change**:

| Setting | Required state | Why |
| --- | --- | --- |
| `VAINAH_MERCHANT_APPROVED` | `approved` | Independent real merchant approval |
| `VAINAH_H1_WRITE_CONTRACT_APPROVED` | `approved` | Independent production H1 write approval |
| `VAINAH_LIVE_FULFILLMENT_APPROVED` | `approved` | Final production fulfillment review |
| `VAINAH_LIVE_CUSTOMER_ACCESS_ENABLED` | `enabled` | Access to own paid entitlement |
| `VAINAH_LIVE_PILOT_ENABLED` | `enabled` | Explicitly opt in to the private pilot |
| `VAINAH_LIVE_PILOT_EMAIL` | verified operator mailbox | Exact allowed purchaser |
| `VAINAH_LIVE_PILOT_OPERATOR_TOKEN` | fresh random 32+ character secret | Separate from sandbox/operator token |

The **public** settings `VAINAH_LIVE_CHECKOUT_ENABLED` and
`VAINAH_LIVE_PAID_E2E_VERIFIED` must remain disabled/unset until the
pilot transaction has been independently reviewed.

## Operating procedure

1. Read the operator-only `/api/shop/operator/production-readiness` report
   with the existing operator token. Check `pilot_checkout_configured`,
   `pilot_callback_processing_configured`, and the boolean-only
   `pilot_missing_requirements`. These are configuration checks, not
   independent merchant or H1Cloud write evidence. No secrets are returned.
2. Authorized operator signs into the allowlisted email account and initiates
   *only one* pilot using the operator-only route and BOTH tokens. No checkout
   URL is ever presented to ordinary shoppers while public sales are disabled.
3. The authorized merchant decides whether to complete the real transaction.
   Do not simulate, forge, or replay paid callbacks.
4. Allow RollyPay to deliver its signed real-payment notification to the
   existing webhook. Do not mark an order as paid manually.
5. Poll `GET /api/shop/operator/live-pilot/status` (same two-token security).
   It reports only payment state, delivery state, whether the signed webhook
   arrived, H1 confirmation and access email delivery — **no** email address,
   secret or VPN subscription link.
6. Verify the exact payment amount/receipt in the merchant account, the H1
   subscription in the panel, the expected verified owner, and email delivery
   from Resend. If any state is `manual_review`, **do not repeat** the H1
   write or the payment.
7. Disable the pilot opt-in after the audit and document actual evidence.
   Only the authorized adult merchant and developer can approve enabling the
   public checkout after successful end-to-end completion.

## Safety reminders

- `VAINAH_LIVE_PAID_E2E_VERIFIED=verified` must **never** be set based on
  code tests or the existing sandbox payment flow.
- Operator-only diagnostics cannot independently establish merchant approval.
  An environment flag is an attestation from a responsible operator.
- This mode deliberately has no endpoint to reset a pilot slot. A repeated
  checkout requires separate reconciliation and a code-reviewed decision.
- Do not use the previously disclosed sandbox token. Rotate it before running
  the pilot; never expose the replacement or pilot token in chat.
