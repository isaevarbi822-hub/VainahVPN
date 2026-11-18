# VainahVPN Android 3.0.0-alpha.6 — HTTPS subscription timeout recovery

Real alpha.5 screenshot on 18 November 2026:
- Imported/cached nodes: **0** in this installation.
- Error: HTTPS timeout, classified as another HTTPS subscription origin.
- Turkey 1/IP cannot be evaluated when the imported subscription list is empty.
- This is a subscription fetch failure, not proof H1Cloud deleted a node,
  and not proof the XHTTP/XMUX engine has failed.

## Fixes
1. Manual refresh: exactly one extra idempotent GET on a classified socket
   timeout, after a bounded 750ms pause. Original HTTPS URL, same client
   identity, strict TLS and same-origin redirects. Never retries HTTP
   authorization errors, rate limits, provider 5xx errors or TLS failures.
   Automatic/background sync still performs a single request.
2. Non-Render HTTPS connect/read timeouts: 12/25 seconds. The exact verified
   Python Render host retains its previously established 12/85 seconds.
3. HTTPS 200 responses with no supported nodes do not replace a previously
   encrypted, working server list. Credentials and cached nodes stay bound
   to the exact saved subscription using Android Keystore AES-GCM.
4. Turkey audit shows one actionable subscription-loading warning instead
   of incorrectly marking both Turkey nodes as missing; the safe status
   is subscription_not_loaded.
5. Anonymized diagnostics: subscription_source (fixed source category),
   subscription_local_nodes (0..50), subscription_refresh_result (whitelisted
   HTTPS/DNS/auth/format failure code). No raw URL, bearer token or VPN key.
6. Isolated Android preview version 3.0.0-alpha.6, version code 305.

## Validation limitations
CI uses synthetic VLESS inputs and the pinned native sing-box-lx schema checker.
It cannot confirm the subscriber's private server URL responds from Norway,
real TLS/VLESS/XHTTP handshakes, or an external Turkish IP.
Separate preview package identities do not share encrypted profile/cache data
from older installations. Never migrate secrets without the user's explicit
authenticated import.

## Device acceptance
Check the same authorized subscription in Happ, then try one manual refresh
on Wi-Fi and one on cellular. If still zero, send only the sanitized report's
subscription_source, subscription_refresh_result and subscription_local_nodes.
Do not send subscription URLs, QR codes, user tokens, UUIDs or private keys.
