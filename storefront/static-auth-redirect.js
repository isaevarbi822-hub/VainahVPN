/* Customer/operator APIs require the Python origin, not the static CDN.
 * Keep the exact path, query, and fragment; never inspect private tokens.
 * This file is static and contains no secrets. */
(() => {
  'use strict';
  const staticOrigin='https://vainahvpn.onrender.com';
  const customOrigins=new Set(['https://vainahvpn.online','https://www.vainahvpn.online']);
  const apiOrigin='https://vainahvpn-python-preview.onrender.com';
  const protectedPaths=new Set(["/account.html","/trial.html","/my-devices.html","/notifications.html","/gifts.html","/referrals.html","/rewards.html","/handoff.html","/operator-grants.html","/operator-pilot.html","/operations.html","/support-operator.html"]);
  if(typeof window==='undefined'||!protectedPaths.has(window.location.pathname))return;
  const origin=window.location.origin;
  if(origin!==staticOrigin&&!customOrigins.has(origin))return;
  const redirect=()=>window.location.replace(
    apiOrigin+window.location.pathname+window.location.search+window.location.hash
  );
  if(origin===staticOrigin){redirect();return;}
  // Custom domain can be attached to either Render Static or Python.
  // Only redirect when it is actually a static host without /api/health.
  void fetch('/api/health',{cache:'no-store',credentials:'omit'})
    .then(async response=>response.ok &&
      response.headers.get('content-type')?.includes('application/json') &&
      (await response.json()).service==='vainahvpn-api')
    .then(isBackend=>{if(!isBackend)redirect();})
    .catch(redirect);
})();
