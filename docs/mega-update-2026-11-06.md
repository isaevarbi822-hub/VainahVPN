# Vainah VPN Mega Update — staged features (2026-11-06)

## Shipping in the development branch

- Account-gated **referrals**: verified-email code, unique invitee attribution,
  self-invite protection, prohibition on referral claims after a paid order.
  No browser-controlled purchase confirmation.
- **Rewards preview**: real paid+delivered live ledger counts excluding pilot
  payments. 10 points per eligible own purchase and 25 per qualified referral
  are **illustrative, not redeemable or guaranteed**. Redeemable balance stays
  zero. No points can extend H1Cloud or change RollyPay bills.
- **Gift drafts**: per-owner, max 5 drafts per day, with status `draft_unpaid`.
  No payment route, valid gift code, or transferable VPN entitlement yet.
- **Notification inbox**: owner-specific expiry and traffic alerts from the
  paid customer overview; read markers are persisted in PostgreSQL; no fake
  "connection lost" claims and no push unless implemented natively.
- **Device limits**: show paid plan cap separately from saved device names.
  Actual sessions/slot usage/disconnection are unavailable without a verified
  provider API and native registration.
- **One-time QR handoff**: 5-minute, one-use token, max three codes per
  15 minutes, stored SHA-256 hash only. Token in QR URL *fragment* (not HTTP
  request path/query), redeemed only by the same verified account and after
  a fresh paid-access check. No VPN key in the QR itself.
- **Vainah Check / status**: uses read-only real control-plane probes. It
  never fabricates server RTT, load, uptime or live payment confirmations.
- **Support center**: private ticket threads and ratings already integrated.

## Not safe to enable yet

1. **Gift purchases/activation** need a distinct RollyPay gift invoice contract,
   signed event verification, an atomic ownership transfer/redeem procedure,
   and independent H1 provisioning with anti-replay.
2. **Rewards redemption** needs an auditable ledger, reversal handling and
   operator-approved promotion rules; preview values are informational only.
3. **Actual device disconnect/slot release** needs verified H1Cloud session
   endpoints and customer-to-device binding. Removing a saved label does
   not affect live VPN traffic.
4. **Smart automatic server selection** needs real client-side measurements
   of per-server RTT, availability and capacity, and a working libbox engine.
5. **Kill Switch and Split Tunneling** are security-sensitive client-native
   features. A website switch cannot enforce them. The Android/Windows/macOS
   VPN client must implement, test and expose the system-level behavior.
6. **Push notifications** require permission, native registration and
   independently verified device delivery, not only a website page.

## Production release safety

- Do not set financial/promotion configuration variables or trigger purchase
  mutations from new customer routes.
- Keep using existing live RollyPay order and H1Cloud fulfillment code.
- Validate CSRF, same-account authorization, browser security headers, no
  subscriber URLs in referrer paths, and one-time redemption.
- Run `cd backend && python -m pip install -e '.[dev]' && pytest -q` before
  claiming a full green release. Render health only proves the app boots.
- GitHub branch: `feat/restore-site-rollypay-checkout`
