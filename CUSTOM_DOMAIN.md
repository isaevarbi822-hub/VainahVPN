# Vainah VPN: custom domain on Render (preview only)

A custom domain makes the existing site easier to find. It does not turn
the Render Free service into an always-on instance or enable real payments.

## Before purchasing

- Choose a short domain that matches the Vainah VPN brand. Names such as
  `vainahvpn.com`, `vainahvpn.net`, or `vainahvpn.no` are **suggestions**,
  not confirmed available names. Check availability and trademark conflicts.
- Check the **renewal** price, not just the first-year promotional price,
  and whether DNS management and WHOIS privacy are included.
- Norway's registry Norid requires a .no private registrant to be 18+.
  A parent or another eligible adult must be the lawful registrant
  for an under-18 project. Follow the registrar's own policies.
- Don't share registrar login credentials, payment details or DNS API tokens.

## Attach to Render

1. Render Dashboard → `vainahvpn-python-preview` → Settings →
   **Custom Domains** → **Add Custom Domain**.
2. Add the purchased host (e.g. `vainahvpn.com`).
3. In the registrar's DNS control panel, follow Render's exact prompts.
   Typical non-Cloudflare DNS examples:
   - `www` CNAME → `vainahvpn-python-preview.onrender.com`
   - `@` A → `216.24.57.1` **only if** the registrar doesn't support
     ALIAS/ANAME or flattening. Cloudflare has separate CNAME guidance.
4. Remove conflicting records (including unwanted AAAA records). Preserve
   MX, SPF, DKIM and DMARC records if the domain has email.
5. Back in Render, choose **Verify**. Render provisions HTTPS automatically.
6. Keep the existing `onrender.com` address online as a fallback.

Render references:
- https://render.com/docs/custom-domains
- https://render.com/docs/configure-other-dns
- https://render.com/docs/configure-cloudflare-dns

## Smoke test after DNS verification

Run in the checked-out repository from Windows or macOS/Linux:

```bash
python scripts/smoke_render.py
python scripts/smoke_render.py --base-url https://YOUR_PURCHASED_DOMAIN
```

The script requires an HTTPS base URL and checks public read endpoints,
expected closed checkout and operator authentication. It never accepts a
merchant API key and only sends a disabled-checkout request if the config
explicitly reports `checkout_ready: false`.

A good test result means the **preview surface** is accessible; it does not
prove real VPN tunnel connectivity, H1Cloud provisioning, merchant settlement,
or webhook delivery.
