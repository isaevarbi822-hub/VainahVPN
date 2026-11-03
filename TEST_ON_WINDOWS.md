# Test Vainah VPN website on Windows

1. Extract the complete preview ZIP into a new folder.
2. Run `start_windows.cmd` (requires Python 3.11+ from python.org).
3. Open `http://127.0.0.1:8765/` in Chrome.
4. Test `/plans.html` and `/checkout.html`.
5. Expand **Тестирование RollyPay · для разработчика** on the checkout page.
6. Copy the automatically generated **Sandbox token** from the command
   window into the token field.
7. Select a tariff, click **Создать тестовый счёт**, then click the
   **Симулировать оплату (без денег)** button.

This is MOCK MODE: no real payment provider request, funds charge, account
creation or VPN activation occurs. The main purchase button is intentionally
disabled until account verification, persistent orders, and actual provisioning
have been implemented and reviewed.

The test server only listens on 127.0.0.1; do not expose it to the internet.
Close its command window or press Ctrl+C when finished.

The ZIP includes the historical site, checkout JavaScript/CSS, backend Python,
and the new Next dashboard under `/app`.

## Testing the actual RollyPay sandbox (no real charge)

Run this only if you have an authorized RollyPay merchant API key.
The test-only creation request ALWAYS sets `test: true`. The application
refuses to open a payment URL unless RollyPay confirms BOTH
`test: true` and `environment: sandbox`. Real checkout stays disabled.

1. Stop the previous local server with Ctrl+C.
2. From the project directory in PowerShell:

```powershell
$secret = Read-Host "Enter RollyPay merchant API key" -AsSecureString
$env:ROLLYPAY_API_KEY = [System.Net.NetworkCredential]::new("", $secret).Password
py -3 .\preview_server.py --rollypay-sandbox
```

3. Open http://127.0.0.1:8765/checkout.html and expand **Тестирование RollyPay**.
4. Copy the *new local sandbox token* printed in the server console. It is
   different on each restart, and NOT the RollyPay API key.
5. Select a plan, create a test order, and open the returned test
   `pay.rollypay.io` form in a **new browser tab**.
6. Confirm the form clearly says **Тестовый режим** and exposes simulation
   controls, **not real payment instructions**.
7. Use the payform's test simulation button only. Return to the original
   checkout tab and click **Проверить статус в RollyPay**.
8. Expect `paid` after successful test simulation. This is a provider
   sandbox status, NOT real funds and NOT issued VPN access.
9. Stop the server and run `Remove-Item Env:ROLLYPAY_API_KEY` in PowerShell.

The local backend checks the merchant API's test markers, amount, order ID,
currency, payment ID and status. If RollyPay responds with a 400/403/502
or fails to confirm sandbox markers, **do not attempt a live payment**.
The `localhost` instance cannot receive remote provider webhooks;
the status refresh tests RollyPay's API instead. Webhook delivery needs a
separate HTTPS test endpoint before any production release.
