// Keep a public plan ID through a same-tab sign-in or OAuth round trip.
(() => {
  const panel = document.getElementById('account-checkout-resume');
  const link = document.getElementById('account-checkout-link');
  if (!panel || !link) return;
  const key = 'vainah.checkout.return-plan';
  const valid = id => typeof id === 'string' && /^[a-z0-9][a-z0-9-]{0,63}$/.test(id);
  const params = new URLSearchParams(location.search);
  let plan = params.get('checkout_plan');
  try {
    if (params.has('checkout_plan')) {
      if (valid(plan)) sessionStorage.setItem(key, JSON.stringify({plan, until: Date.now() + 30 * 60 * 1000}));
      else sessionStorage.removeItem(key);
    } else {
      const saved = JSON.parse(sessionStorage.getItem(key));
      if (saved && saved.until > Date.now()) plan = saved.plan;
      else sessionStorage.removeItem(key);
    }
  } catch { /* The explicit return link also works when storage is disabled. */ }
  if (!valid(plan)) return;
  link.href = 'checkout.html?plan=' + encodeURIComponent(plan) + '#shop-payment-panel';
  link.addEventListener('click', () => {
    try { sessionStorage.removeItem(key); } catch { /* Storage is optional. */ }
  });
  panel.hidden = false;
})();
