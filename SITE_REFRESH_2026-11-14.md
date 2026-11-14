# Vainah VPN — production refresh checklist (2026-11-14)

## Actual deployment sources
- Static Render service: `VainahVPN` / `https://vainahvpn.onrender.com`
- Python Render service: `vainahvpn-python-preview` / `https://vainahvpn-python-preview.onrender.com`
- Both services currently track `feat/restore-site-rollypay-checkout`, **not** `main`.
- Keep this refresh branch isolated until regression checks pass.

## Read-only smoke check
Run `python scripts/audit_public_site.py`. This performs only public GET requests.
Validate HTML, robots.txt Allow rule, sitemap public URLs, backend health and
shop config boolean `checkout_ready`. A false readiness flag is not downtime.
If network checks are inconclusive, do not announce an outage.

## Before changing the storefront
1. Inventory and remove stale content **only after** identifying canonical source.
2. Compare storefront plan labels against backend authoritative plan catalog.
3. Preserve existing checkout, paid orders, webhook signature verification,
   idempotency, H1Cloud issuance, receipt emails and user sessions.
4. Keep account and checkout navigation on the Python origin.
5. Verify no account pages, payment pages or API routes appear in sitemap.
6. Run `cd backend && python -m pytest -q` and the browser regression suite.
7. Check 320, 375, 390, 768, 1024 and 1440 pixel widths and keyboard navigation.
8. Confirm trial, gift cards, support and renewal reminders with safe mocks.
9. Never use live checkout or real payments for UI smoke tests.
10. Merge/deploy only after reviewing changes and observing green checks.

## Future feature batches
- Fresh content: centralized pricing, feature availability and honest status labels.
- UX: accessible navigation, responsive layout, motion preferences and loading states.
- Account: subscription status, devices, orders, email support and renewal preferences.
- Integrations: non-secret diagnostics for RollyPay, H1Cloud, email and login.
- Reliability: friendly error codes, request retries, accessibility and SEO regression.

Do not claim untested functionality is working or that a deployment occurred.
