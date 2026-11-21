# Vainah VPN — Render-only deployment

This repository is the source for the public website and FastAPI backend.

- Public preview: https://vainahvpn-python-preview.onrender.com/
- Render blueprint: `render.yaml`
- Build: `cd backend && pip install -e .`
- Start: `cd backend && uvicorn vainah.main:app --host 0.0.0.0 --port $PORT`
- Health: `GET /api/health`
- Deployed revision: health exposes a validated `commit_sha` from Render's
  `RENDER_GIT_COMMIT` variable (null if unavailable). Verify it with
  `python scripts/smoke_render.py --expected-commit <full-40-character-SHA>`.
- Public tariffs: `GET /api/shop/plans`
- Database connectivity: `GET /api/site/services`
- Storefront: `storefront/`; Python API: `backend/vainah/`

The old serverless routes and hosting-specific form handlers are not used.
Preview account sign-in and support ticket submission remain disabled until
secure server-side integrations are implemented; they must not mimic successful
logins or form submissions.

Render environment: `DATABASE_URL` points to the PostgreSQL instance;
never commit it, other API keys, operator tokens or VPN subscription links.

Live checkout remains disabled by design. Sandbox ledger, RollyPay and
H1Cloud provisioning are separate features and require additional
verification before any real customer payments.

To deploy a revision: Render Dashboard → Web Service → Deploys →
Manual Deploy → Deploy latest commit. Avoid repeatedly launching builds;
the provider may cancel a superseded deployment.
