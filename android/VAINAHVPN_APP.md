# VainahVPN — Android application

**User-facing app name: VainahVPN** (no "Next", "Preview", or secondary name on the launcher).

This is the existing native Android VPN client upgraded in place, **not a browser-only mock-up**. The application uses Android `VpnService`, a subscription loader backed by Android Keystore, and the libbox tunnel engine when compiled with `-PvainahEnableLibbox=true`.

## App sections

1. **Главная** — actual native service state, connect/disconnect, selected server, live libbox traffic counters when provided, and quick links to server collections.
2. **Серверы** — real nodes fetched from the saved H1Cloud-compatible HTTPS subscription. Browse/search and select, country flag/name, tested entry-point TCP latency where measured, favorites, sort, and category chips.
3. **Защита** — native Android Always-on/lockdown settings and working per-app bypass (split tunneling) through the native VpnService configuration, subject to Android lockdown restrictions.
4. **Подписка** — securely saved VPN profile and direct links to the production website for current prices, payment, subscription validity, and renewal.
5. **Профиль** — website account login, devices, support, gifts, notifications, and native settings.

## Server categories

`ServerCollections.kt` filters **only nodes actually present in the loaded subscription**. The public UI labels are: Все, Рекомендуемые, Быстрые, Игры, Стриминг, Белые списки, Избранные.

- **Белые списки:** only nodes whose *non-secret subscription label* explicitly includes e.g. `Белые списки` or `Whitelist`. This category **does not** synthesize WhiteList Secure/Fast/Trusted or add servers in H1Cloud. The provider must publish the nodes in the subscription. It makes no claim about bypass capabilities or site compatibility.
- **Игры / Стриминг:** similarly based only on words in the subscription labels. This is not a guarantee the game/service works.
- **Быстрые:** only endpoints with real, sufficiently repeated TCP connection measurements. These are **not** VPN tunnel ping, traffic speed, actual server load, or uptime monitoring.
- **Рекомендуемые:** user favorites or entries with measurements, without invented rankings. The app never displays synthetic ping/load.
- **Избранные:** selection is stored as hashed server identities in encrypted app storage, not plaintext VLESS credentials.

The country-name/flag dictionary is **display-only**. Countries appear only for loaded nodes and never generate fake endpoints.

## Two kinds of "white list" are different

**Server whitelist group** is a filter of provider-labelled servers. **Per-app whitelist** (Android split tunneling) exempts chosen apps from the VPN. These apps use the normal device network and are not tunnel protected. By default there are no exceptions. Exclusions require a working libbox build, take effect upon reconnect, and are disabled under Android's lockdown mode.

Domain-based selective routing is **not active** in this revision. Do not tell customers a website-level whitelist is already filtering their traffic.

## Subscription, login and payments

The native client can import an issued HTTPS subscription URL or a supported VLESS/TCP/REALITY key. Tokens and credentials are never printed in server rows.

The profile, legal checkout, receipts, and customer support live on the official Python backend at `https://vainahvpn-python-preview.onrender.com/`. The Android app opens fixed HTTPS pages using a browser intent. **It does not collect card data or fabricate user balances**, does not independently issue subscriptions, and does not enable the unverified Platega checkout. RollyPay and H1Cloud remain controlled by the existing backend.

## Development and validation

Run the connected GitHub Actions workflow **VainahVPN Android**, or locally with Gradle 8.11.1 / JDK 17 / Android SDK 35:

```bash
gradle -p android -PvainahEnableLibbox=true -PvainahIsolatedPreview=true :app:clean :app:assembleDebug :app:testDebugUnitTest --no-daemon --stacktrace
```

The artifact is an *isolated preview app ID* to avoid silently replacing the existing installed VPN. The launcher label remains **VainahVPN**, including previews.

Tests cover categories, whitelist-label matching, favorites, real TCP observations and missing-server empty states, plus existing subscription security and libbox integration contracts.

A green CI run verifies compilation and local tests **only**. Real end-to-end VPN connection, Wi-Fi-to-cellular handoff, DNS/IPv6 routing, iOS support and platform-restricted settings still require on-device testing. Do not claim they have been confirmed by a build job. Windows/iOS clients are separate later milestones; this PR does not create them.
