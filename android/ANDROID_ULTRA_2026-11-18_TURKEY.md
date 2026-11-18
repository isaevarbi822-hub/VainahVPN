# VainahVPN Android 3.0.0-alpha.4 — Turkey diagnostics

Date: 18 November 2026. Debug preview, isolated application ID
`app.vainah.vpn.next.preview`. This is **not** a verified production fix
for two real Turkish VPN endpoints.

## Changes

- Accept both `Турция 1`, `Турция IP` and the separator variants
  `Турция · 1`, `Турция · IP`, plus exact Turkey/Türkiye aliases.
  Never match `Турция 10` or create a missing server.
- Add **local** profile audit for both exact nodes in **Servers** and
  **Diagnostics**. Show one of three distinguishable states: absent from
  subscription, rejected by local parser, or parseable and ready for an
  *attempt*. None of those states verifies a handshake or data egress.
- Include only fixed anonymous status strings
  `turkey_1_local_profile` and `turkey_ip_local_profile` in the
  copied diagnostic report, never links/hosts/IP/UUID/keys.
- Replace the misleading instruction to refresh subscription when the
  selected profile format itself is unsupported.
- Carry the unmerged sing-box-lx v1.14.4 XMUX/XHTTP/REALITY local fixes
  reviewed in PRs #93–#94 into a new isolated preview build.
- Leave RollyPay, Platega, H1Cloud website, customer orders, and all
  real server-side config unchanged.

## Required physical device acceptance

The synthetic CI config suite cannot tell us if real nodes **Турция IP**
and **Турция 1** actually negotiate with their VPN servers. For each
entry on Android: import the authorized subscription, confirm the node
exists, run local audit, select it, run the existing 3-attempt selected
TCP check *while disconnected*, connect, and verify an external IP and
real HTTPS connectivity **in the browser**. A reachable TCP port is
not proof of a successful VLESS/REALITY/XHTTP handshake.

If the selected profile still fails, share only the app's anonymized
diagnostic report, not the URL, QR code, UUID, REALITY key, or H1Cloud
administrator credentials. A missing profile must be fixed at the
operator's H1Cloud source; a rejected profile needs protocol compatibility
investigation, not another payment or repeated subscription refresh.

## Release gates

PR CI must succeed with the pinned native AAR SHA-256 check, synthetic
VPN schema checks, JVM tests and APK assembly. An explicitly pushed
`android-preview-*` tag can publish a prerelease APK/checksum only
after those gates. Debug previews may be signed with a different key
from a previous APK, and should not be claimed to update a production
application in place.
