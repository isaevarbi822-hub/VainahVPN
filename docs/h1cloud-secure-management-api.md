# H1Cloud DE12: secure management API gate

Status as of 2026-11-04: Render can reach the public **unauthenticated** node
health endpoint `http://direct-de12b.h1cloud.net:25105/api/health`. The
original node HTTPS URL `https://s-25105.de12.h1clayd.click/api` times out
from Render. The direct endpoint **does not negotiate HTTPS** on port 25105.
These facts establish only network reachability, not safe credential transport.

## Why live delivery is still blocked

H1Cloud's node API requires a powerful bearer token for GET/POST/PATCH calls.
Sending `PANEL_API_TOKEN` to a public plain-HTTP endpoint permits interception
or tampering of the token and customer subscriptions. A reverse proxy with an
HTTPS **frontend** is not an end-to-end fix if its upstream hop to the node
remains plain HTTP across the public internet.

The node advertises:
- `GET /api/info?name=NAME` — client status (read)
- `POST /api/create` — create subscriber
- `PATCH /api/edit` — extend subscriber

Routes are now aligned in VainahVPN, but **response payloads and actual writes
remain unverified against an authenticated, securely connected node**.

## Approved ways forward

1. Ask H1Cloud to expose a valid **HTTPS API management endpoint reachable from
   your Render region** (not merely a VPN Reality listener). Ensure its
   certificate is valid for the exact hostname, and test read-only authorized
   client lookup before any live writes.
2. If you administer the node itself (console/SSH access), a correctly
   configured **on-node TLS termination** can protect the complete public
   transport. The API must be accessible to the local proxy through a local
   loopback or otherwise verified private network, not a public plain HTTP hop.
   This needs provider-confirmed port and DNS/certificate setup; do not reuse a
   VPN Reality TLS port as a generic web API.
3. For a node using a private certificate authority, VainahVPN accepts its
   **trusted CA certificate** through `PANEL_TLS_CA_PEM` in Render:
   ```text
   -----BEGIN CERTIFICATE-----
   ...public CA certificate PEM provided by your trusted operator...
   -----END CERTIFICATE-----
   ```
   Set `PANEL_BASE_URL=https://<actual-verified-host>:<port>/api` and retain
   `PANEL_API_TOKEN` in Render's environment only. Certificate and hostname
   validation remain enabled. A PEM CA does **not** enable HTTPS on the
   HTTP-only direct port. Never paste a private key into this environment
   variable. Do not use a self-signed CA from an unverified source.

## Deployment checks

- `GET /api/site/services` reports `h1_direct: ok` only for the public,
  tokenless direct-health request; `protected_connection: false`.
- `h1: ok` requires a successful authenticated read-only request over
  properly verified HTTPS. A config-valid `PANEL_BASE_URL` alone is not enough.
- Real checkout and automatic issuance stay disabled until the HTTPS
  transport, actual API response schema, authenticated read, operator-approved
  one-time create/extend test, webhook delivery, and legal merchant readiness
  have all been verified. Do not change these gates to bypass an untrusted hop.

No real customer data, tokens or keys should be shared in support messages.
