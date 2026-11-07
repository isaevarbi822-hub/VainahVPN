# Vainah VPN — renewal reminders

The customer UI stores a verified-email opt-in. The protected runner can
send renewal reminders only after explicit server-side activation. On-site
account alerts for 7, 3 and 1 days before H1Cloud expiry are independent
of scheduled email delivery and do not require email opt-in.

## Safety gates

- `VAINAH_REMINDER_DELIVERY_ENABLED=true` in Render (default: disabled)
- `VAINAH_REMINDER_RUNNER_KEY` in Render: a separate, random secret of at
  least 40 characters (never reuse `SESSION_SIGNING_KEY`)
- GitHub Actions secret `VAINAH_REMINDER_RUNNER_KEY`: same private value
- `VAINAH_REMINDER_SCHEDULE_CONFIRMED=confirmed` in Render **only after**
  the scheduled workflow is registered on the repository default branch,
  checked, and a controlled send has succeeded; otherwise the UI correctly
  reports email delivery as not scheduled
- `DATABASE_URL`, `RESEND_API_KEY`, `VAINAH_EMAIL_FROM`,
  `SESSION_SIGNING_KEY` and H1Cloud HTTPS settings must already work
- Email reminders are **not active** until the above are deliberately set
  and the workflow schedule is registered on the repository's default branch

The `renewal-reminders.yml` scheduled workflow runs around 09:15 UTC,
but GitHub scheduled workflows only run from the repository's default
branch. While this file exists only in the deployment feature branch,
the schedule is **not active**. Do not merge the entire deployment branch
into `main` solely to activate the schedule.

## Verified delivery

Dispatcher selects up to 15 latest real paid-and-delivered accounts expiring
within seven days, excludes owners with refunds/chargebacks, checks the
verified email-derived owner reference, rechecks active H1Cloud client state
and exact expiry, and verifies consent. For each expiry and threshold (7/3/1
days), PostgreSQL records one atomic claim. A failed/unknown email delivery
is **not automatically retried**: investigate it instead, because a retry
could duplicate the email. No subscription URL is included in the message.

The endpoint `POST /api/internal/reminders/run` requires the private
`X-Vainah-Reminder-Key` header; never put it in a URL, commit, screenshot,
or browser JavaScript.

Before activating, run `cd backend && python -m pytest -q`, test opt-in
and opt-out on separate verified accounts, inspect Render deploy status,
and verify one controlled test delivery. Keep the server gate disabled until
the owner explicitly authorizes live reminder delivery.
