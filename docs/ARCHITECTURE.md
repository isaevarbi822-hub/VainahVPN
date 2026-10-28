# Vainah VPN · Architecture and release gates

## Data-flow

```
Browser preview -> Python FastAPI (no credentials / no personal data)
Android app -> Clerk sign-in -> backend verifies JWT -> user's authorized H1Cloud data
Android app -> local secure subscription store -> Android VpnService -> libbox (Go)
                        |                                |
                  validation & errors                tunnel + stats
```

**In this commit only the first preview path and offline VLESS inspector are implemented.**
The rest is a planned integration, not an API that already works.

## Why Python cannot be the Android VPN engine

The Android operating system requires a native `VpnService` handling a TUN interface, lifecycle, notification, and network changes. sing-box `experimental/libbox` is written in Go and exported to Android through `gomobile bind` (and a native extension on Apple devices). Python remains the control-plane web backend.

Official upstream:
- https://github.com/SagerNet/sing-box
- https://github.com/SagerNet/sing-box-for-android
- https://sing-box.sagernet.org/installation/build-from-source/

Do **not** embed unverified third-party AAR binaries, dynamic downloaded executables, or a hard-coded imaginary libbox version. Review upstream licensing (GPLv3) before publishing derivatives.

## API preview contracts

- `GET /api/health` — alive, version, preview mode
- `GET /api/v1/overview` — safe empty account/subscription states
- `GET /api/v1/locations` — [] until real H1Cloud integration
- `GET /api/v1/diagnostics` — truthful component checks
- `GET /api/v1/platforms` — planned platform support
- `GET /api/v1/security` — security properties, no private values
- `POST /api/v1/import/inspect` — local VLESS/Base64 format check, HTTPS link recognition only

No login/checkout endpoints are exposed until provider JWT/webhooks and authz tests are ready.

## Required next pieces

1. Validated Clerk JWT verification (issuer, audience, expiry, signing keys), link to own DB account; no trusting user IDs from request bodies.
2. Database migrations and customer-scoped queries, access-control tests.
3. H1Cloud adapter with documented API, timeouts, redacted exceptions, subscription expiry and device mapping; distinguish 403 from actual expiry.
4. Native Android project, `VpnService`, build of compatible libbox, local encryption, flow state machine; no "connected" until OS VPN and egress tests pass.
5. Add 403 / TLS / DNS / IPv6 / captive portal / Wi-Fi handover diagnostics and native integration tests.
6. RollyPay verified webhook signatures, idempotency, replay protection, server-validated pricing. Keep disabled until reviewed.
7. App signing, store policy, privacy policy and licensing review.

## Security rules

Never put subscription URLs/tokens in server logs, telemetry, exception details or screenshots. Never disable HTTPS certificate verification. Native VPN credentials should remain device-local and encrypted. Browser demo cannot start a remote device tunnel. Manage service account secrets only in hosting environment.
