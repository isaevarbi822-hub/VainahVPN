/* Customer/operator APIs require the Python origin, not the static CDN.
 * Keep the exact path, query, and fragment; never inspect private tokens.
 * This file is static and contains no secrets. */
(() => {
  'use strict';
  const staticOrigin='https://vainahvpn.onrender.com';
  const apiOrigin='https://vainahvpn-python-preview.onrender.com';
  const protectedPaths=new Set(["/trial.html","/my-devices.html","/notifications.html","/gifts.html","/referrals.html","/rewards.html","/handoff.html","/operator-grants.html","/operator-pilot.html","/operations.html","/support-operator.html"]);
  if(typeof window==='undefined'||window.location.origin!==staticOrigin||
     !protectedPaths.has(window.location.pathname))return;
  window.location.replace(
    apiOrigin+window.location.pathname+window.location.search+window.location.hash
  );
})();
