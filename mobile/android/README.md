# Android · native VPN engine (not connected yet)

The Android VPN is **not** implemented by Python. Use upstream sing-box `experimental/libbox` through maintained official build tooling, with a Kotlin/Java `VpnService` and `gomobile`-generated binding.

## Required modules

- `app/ui`: Compose screens; connection status is read from native engine.
- `app/subscription`: HTTPS import, HTTP 403/timeout/retry diagnostics, encrypted local store, URL and Base64 VLESS parsing.
- `app/vpn`: Android `VpnService`, TUN fd handoff to libbox, foreground service notification, start/stop and clean recovery.
- `app/observability`: traffic counters, latency, resolved outbound, DNS/IPv6 leak tests, network change events.
- `app/auth`: Clerk sign-in and backend JWT; never package Clerk secret key.
- `app/billing`: disabled until verified backend order/webhook infrastructure.

Native connection state machine: `idle -> preparing -> connecting -> connected -> reconnecting/failed -> disconnecting -> idle`.
Only emit `connected` after the OS tunnel is active **and** the configured egress probe succeeds. On engine crash, report `failed`, close stale VPN interface and allow safe retry.

## Why there is no copied AAR or pretend "finished APK"

The official libbox APIs and build tags are version-dependent. Bind against a reviewed upstream commit, review GPL obligations, and compile/test on supported Android ABIs. Work must include actual Android permission, routing and mobile-network tests; neither Python tests nor a web UI prove that the native VPN works.

Sources:
- https://github.com/SagerNet/sing-box/tree/dev-next/experimental/libbox
- https://github.com/SagerNet/sing-box-for-android
- https://sing-box.sagernet.org/installation/build-from-source/
