# Signed sandbox provisioning: fixes and rollout

Scope: `feat/restore-site-rollypay-checkout`, starting at `ba0c3c5e1fd30c2433be9ce9ccfbc1c2259aea71`.

## Confirmed causes

- **Early callback / UNKNOWN_ORDER:** provider creation previously preceded durable order insertion. A callback reaching another worker before the create response had no order to find. The checkout now commits a `pending:` reservation before the network POST, binds the validated response atomically, and returns retryable HTTP 503 while binding is pending. Existing per-order PostgreSQL lookup already addresses a stale process cache; owner listing now also reads PostgreSQL rather than the process snapshot.
- **Unproven paid state:** `webhook_received` meant any signed event, including `payment.created`. Subsequent GET polling could make status paid while leaving that generic flag true. Fulfillment and receipts now require the separate `paid_webhook_received` proof, set exclusively by a verified paid callback. No historical backfill infers this proof.
- **Stalled safe failures:** preflight/configuration failures before an H1 write were permanently quarantined, and callbacks were acknowledged with HTTP 200. These now persist `failed_before_write` and return retryable 503. The next signed callback can safely reclaim that state. `claimed`, `issued`, and `needs_review` never automatically start another provider write.
- **Insufficient H1 postcheck:** a merely future expiration did not prove the purchased duration. Postchecks now verify duration, device limit, identity, account state and subscription URL; malformed profiles fail safely.
- **Concurrent first-use SQL migration:** real PostgreSQL tests reproduced a CREATE TABLE race between fresh workers despite IF NOT EXISTS. Transaction-scoped advisory locks serialize schema initialization.
- **Cabinet visibility:** per-order sandbox identities were absent from the live subscription view. A separate, clearly labeled sandbox section now exposes owner-filtered status; private links are fetched only through the owner-protected access endpoint. Delayed live or sandbox access responses are discarded after an account switch.
- **Receipt timing and recovery:** auto-issuance receipts wait for verified issuance. An active receipt lease returns retryable 503 until durable completion, so a crashed sender does not terminate provider retries. Per-attempt tokens prevent an expired sender from completing or releasing a newer worker's lease.
- **Concurrent refund and stale saves:** the SQL update now returns the actual committed status and guards immutable order/payment/owner/plan bindings. The process response adopts that state instead of returning its stale proposed paid status. H1 eligibility is rechecked after the awaited preflight; a final signed-paid compare-and-set guards persistence/access. This cannot atomically coordinate a provider write with a refund on another system; a reversal during an in-flight write still requires reconciliation.
- **Private links surviving refresh/logout:** explicit session and refresh generations prevent late responses from restoring stale access. Refreshed refund/revocation and logout immediately remove private href/copy data and active subscription labels, including same-object reauthentication and overlapping refreshes.
- **Other first-use SQL races:** independent real-PostgreSQL tests reproduced catalog uniqueness failures in live checkout and email OTP schema creation. Both now serialize schema initialization while preserving OTP cooldown, attempt limits and single-use verification.
- **Database lock waits:** transaction-scoped query and lock timeouts bound blocked SQL work. Failures remain sanitized and retryable instead of leaving requests waiting indefinitely.

The local SQLite ledger now also reloads cross-worker state, preserves terminal statuses and immutable identity, closes its connections, and sanitizes failures. Signed-paid filtering precedes pagination so newer pending orders cannot hide an already issued subscription.

RollyPay amount/currency/sandbox mismatch guards remain strict. The baseline already accepted exactly equivalent decimal RUB representations; this change does not assume that production provider errors have the same cause without their response evidence. Contradictory aliases/test markers and malformed event types are rejected. The exact historical Render `PROVIDER_*` errors cannot be attributed without deployment evidence.

`h1_direct` is an optional **unauthenticated HTTP health probe**, separate from the authenticated HTTPS management API. It now reports safe reason codes, including tokenless 401/403 rejection, timeout and contract mismatch. No live response was available to confirm the specific Render failure.

## Validation

From `backend`, use Python 3.12 with the project's `[dev]` dependencies:

```sh
VAINAH_TEST_DATABASE_URL='postgresql:///vainah_test?host=/workspace/.local&port=55432' python -m pytest -q
ruff check vainah tests
python -m compileall -q vainah
```

VAINAH_TEST_DATABASE_URL must reference a dedicated test database: integration fixtures create/drop isolated schemas. CI now starts PostgreSQL 17 and Node 24, so database tests execute instead of being skipped. Node is also used for DOM/network regression tests that verify private URLs cannot appear after switching accounts. Without the test DSN, PostgreSQL tests are explicitly skipped; that is not full validation.

Render health now reports only a validated full `RENDER_GIT_COMMIT` as `commit_sha` (null when unavailable). `python scripts/smoke_render.py --expected-commit <full-SHA>` checks the actual deployed revision. The checker accepts an enabled operator sandbox while requiring production checkout disabled; malformed public data is reported without echoing response bodies or invoking checkout.

The end-to-end test uses real OTP/session verification, actual PostgreSQL transactions, signed HTTP callbacks and owner access checks. RollyPay, H1Cloud and outgoing email are mock transports. It proves a valid paid callback creates one H1 user and one accurate receipt, repeated callbacks do not write again, invalid inputs do not issue, links are encrypted at rest, and foreign/anonymous accounts cannot retrieve them. Further tests cover database failure/rollback, first-use concurrency, stale state, ambiguous H1 writes and safe pre-write retries.

Local FastAPI smoke checks validate health, the six RUB tariffs, storefront/account pages, database health, anonymous sandbox rejection and disabled production checkout. This does not prove a live VPN tunnel, deliverability of real email, provider integration, remote GitHub Actions success, or Render deployment.

Final local result: **462 passed, 0 failed, 0 skipped** (one upstream Starlette/httpx deprecation warning). Ruff, backend compile/import checks, five JavaScript syntax checks, workflow YAML checks and the local HTTP functional smoke all passed. Python 3.12.14, PostgreSQL 17.11 and Node 24.22.1 were used. The reusable installation script was exercised repeatedly.

## Safe rollout and reconciliation

1. Review the commit and CI. Keep production gates disabled and preserve the already confirmed Render sandbox settings. Do not create duplicate settings or put credentials in logs/Git. Confirm an appropriate database backup exists before deployment; onboarding has not made a production backup.
2. Deploy the reviewed commit to the named Render service through the existing workflow. Additive migrations run on database access: `paid_webhook_received` defaults FALSE, receipt claims gain `receipt_claim_token`, and the H1 state constraint gains `pending` and `failed_before_write`. Existing rows/claims are preserved.
3. Legacy `paid + webhook_received` orders are deliberately ineligible until a fresh verified signed PAID callback or reviewed reconciliation supplies reliable evidence. Do not bulk-set the proof flag from GET status or browser data. Previously claimed/uncertain orders remain locked regardless of their age.
4. A `pending:` reservation after an ambiguous provider creation/binding failure preserves the order identity, but needs reconciliation against the original provider operation. Do not blindly resend the invoice-creation POST or attach a payment ID supplied by the browser. An H1 `claimed`/`needs_review` entry requires panel reconciliation before any further write; no automatic retry/reset is implemented for ambiguous writes.
5. After deployment, compare the actual Render deployed commit SHA with the reviewed Git commit. Verify public health, production gates, signed sandbox payment, exactly one provider user with correct term/device limit, owner-only cabinet access and the actual receipt. Replay the callback and verify no additional provider user. This live sandbox acceptance has not been executed by the automated tests.
6. If rollback is necessary, disable the sandbox auto-issuance feature first. Do not roll back to code that trusts the generic webhook flag while leaving automatic issuance enabled. Do not remove durable claims or paid proof to force a retry.

The cloud environment saves setup/start instructions separately from repository code. A configuration draft save does not execute setup, apply network rules, publish a snapshot, trigger CI, or deploy Render. Remote GitHub API and Render health checks were blocked by the current network policy; the required domains are saved in the environment draft.

## Changed files

- `.github/workflows/python-ci.yml`
- `RENDER_ONLY.md`
- `backend/tests/conftest.py`
- `backend/tests/test_account_dashboard.py`
- `backend/tests/test_account_sandbox.py`
- `backend/tests/test_api.py`
- `backend/tests/test_auth_live_postgres.py`
- `backend/tests/test_billing.py`
- `backend/tests/test_h1_direct_health.py`
- `backend/tests/test_h1_live_provision.py`
- `backend/tests/test_live_checkout_routes.py`
- `backend/tests/test_live_fulfillment_integration.py`
- `backend/tests/test_postgres_integration.py`
- `backend/tests/test_postgres_ledger.py`
- `backend/tests/test_receipt_email_flow.py`
- `backend/tests/test_rollypay_sandbox_lifecycle.py`
- `backend/tests/test_sandbox_auto_h1.py`
- `backend/tests/test_smoke_render.py`
- `backend/vainah/billing.py`
- `backend/vainah/config.py`
- `backend/vainah/customer_portal.py`
- `backend/vainah/email_auth.py`
- `backend/vainah/h1_direct_health.py`
- `backend/vainah/h1_live_provision.py`
- `backend/vainah/live_checkout.py`
- `backend/vainah/live_ledger.py`
- `backend/vainah/main.py`
- `backend/vainah/postgres_ledger.py`
- `backend/vainah/sandbox_auto_h1.py`
- `backend/vainah/sandbox_ledger.py`
- `docs/PROVISIONING_FIX_VALIDATION.md`
- `scripts/smoke_render.py`
- `storefront/account-dashboard.js`
- `storefront/account.html`
