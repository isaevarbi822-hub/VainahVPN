# Android 3.0.0-alpha.5 — Turkey XHTTP/XMUX follow-up

Device report (18 November 2026) from **3.0.0-alpha.4**:
- 41 subscription entries loaded.
- `native_xhttp_enabled=yes`.
- `turkey_1_local_profile=not_in_subscription` meant only that the
  requested **label** was not found, not that the server was proven absent.
- `turkey_ip_local_profile=local_profile_rejected_xhttp_xmux_unknown_field`.
- `phase=off`, so no native VPN handshake or data egress was tested.

## Safe compatibility changes
- Accept exact Turkey 1/IP labels with additional separators (bar, #, numero)
  and Turkish flag **without** inventing missing H1Cloud nodes.
- Missing entry now reports `not_found_by_label` with explicit advice to
  inspect all Turkish subscription rows, rather than falsely saying H1Cloud
  had no server. The button to inspect imported Turkish nodes works even
  when neither requested exact label is found.
- Match recognized XMUX field names regardless of capitalization (like
  Go's JSON unmarshalling). Interpret a `#knownXMUXField` as inactive
  Xray JSON configuration metadata **only when the rest of the key matches
  the known six-field XMUX schema**. Unknown active options, unknown
  commented keys, incompatible ranges, and aliases with conflicting
  values continue to fail closed. No network-relevant field is guessed.
- Bump isolated Android preview version to alpha.5 (code 304).

## What CI can and cannot prove
CI runs a Kotlin/Android test suite, generates synthetic VLESS profiles
and checks them with the pinned sing-box-lx core. It cannot verify a
customer's real H1Cloud subscription, specific node handshake,
actual TLS/XHTTP traffic, public IP or throughput.

The second failed profile could contain a different genuinely unsupported
XMUX key. If the same error remains in alpha.5, a **server-authorized**
operator must inspect the XHTTP `extra.xmux` field names locally in
H1Cloud (not share bearer URLs or keys). Keep server/client parameters
aligned, never silently delete unrecognized active options. Do not buy
another subscription solely to diagnose an engine-format error.
