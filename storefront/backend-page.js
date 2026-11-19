/* Run before the page scripts on storefront pages that need the Python backend. */
(() => {
  'use strict';
  if (location.origin !== 'https://vainahvpn.onrender.com') return;
  const destination = new URL(location.href);
  destination.hostname = 'vainahvpn-python-preview.onrender.com';
  location.replace(destination.href);
})();
