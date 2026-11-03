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
