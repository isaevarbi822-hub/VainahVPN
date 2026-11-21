# Vainah VPN — email identity and avatar

## What is deployed

- Every transactional email uses a branded responsive HTML layout (with a
  plain-text alternative), a real static image, and the existing secure
  Resend sending pipeline.
- The sender shows as Vainah VPN. Its actual email address is unchanged
  and still comes exclusively from the verified-domain VAINAH_EMAIL_FROM
  setting on the Python Render service. Changing From to an unverified domain
  would break real customers' OTP, receipts and support notifications.
- The avatar inside the email header is hosted at
  https://vainahvpn.onrender.com/email-avatar.png
- All email links to account management use the backend website that owns
  the signed authentication cookies.
- Optional VAINAH_EMAIL_SENDER_NAME may be set to Vainah VPN Support
  (ASCII letters, digits, dots, hyphens and spaces, 2–50 characters).
- Optional VAINAH_EMAIL_REPLY_TO may be set to a working response mailbox.
  Configure this only after its address is live.

## To obtain a professional mailbox address

1. Purchase or use a domain you control.
2. Verify this domain in Resend, including the DNS records Resend requires
   for sending (DKIM/SPF and any applicable return-path settings).
3. Publish DMARC for the sending domain; test authentication/alignment.
4. Create the selected mailbox or alias in your email provider.
5. Only then change VAINAH_EMAIL_FROM to the verified sender, for example
   Vainah VPN <hello@your-domain.example>. Test a real inbox and spam
   classification before enabling it for customers.
6. Use VAINAH_EMAIL_REPLY_TO only when responses can be received.

## About the avatar next to a message in Gmail, Outlook or Apple Mail

The email header logo is controlled by the HTML template. The inbox list
avatar is controlled by the recipient's mail provider; it cannot be
guaranteed by an HTML image or an arbitrary Resend setting. Some providers
recognize account profile photos; some support BIMI with authenticated DNS
and additional eligibility/certificate requirements. Use provider-specific
documentation when your custom domain has been configured.

## Safety

Do not put credentials, personal subscription URLs, passwords or
verification codes in the image URL, logo metadata, tracking pixels or
subject lines. Do not change Resend authentication or the email delivery
idempotency identifiers when making visual changes. Run the tests in
backend/tests/test_email_branding.py and the existing email tests.

## Domain cutover note

Customer authentication, checkout, and private subscriptions are same-origin
Python endpoints. If vainahvpn.online is attached to Render Static, browser
navigation is temporarily routed to the Python service; public read-only
endpoints use an explicitly enumerated CORS allowlist. To serve everything
under the branded host, attach the custom domain to the Python Render web
service instead of the static site, and point its DNS to that service. Never
proxy authenticated POSTs or cookies across CDN origins. Preserve the old
Render URL until payment callback and sign-in tests pass.
