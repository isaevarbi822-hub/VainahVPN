/* Preview-only account login: show honest availability; do not collect codes. */
(() => {
  'use strict';
  const root = document.getElementById('account-auth-panel');
  if(!root) return;
  const tabs = [...root.querySelectorAll('[data-auth-tab]')];
  const panes = [...root.querySelectorAll('[data-auth-pane]')];
  const status = root.querySelector('[data-auth-availability]');
  const message = 'Вход по Telegram и электронной почте появится после подключения защищённой авторизации к Python API на Render.';
  const select = method => {
    for(const tab of tabs) {
      const active = tab.dataset.authTab === method;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
    }
    for(const pane of panes) pane.hidden = pane.dataset.authPane !== method;
  };
  for(let i=0; i<tabs.length; i++) {
    tabs[i].addEventListener('click', () => select(tabs[i].dataset.authTab));
    tabs[i].addEventListener('keydown', event => {
      if(event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      const next = (i + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length;
      tabs[next].focus();
      select(tabs[next].dataset.authTab);
    });
  }
  for(const form of root.querySelectorAll('form')) {
    form.addEventListener('submit', event => event.preventDefault());
    for(const element of form.querySelectorAll('input, button')) element.disabled = true;
  }
  const widget = document.getElementById('account-widget');
  if(widget) widget.textContent = 'Telegram Login временно недоступен.';
  const retry = document.getElementById('account-telegram-retry');
  if(retry) retry.disabled = true;
  for(const el of root.querySelectorAll('[data-auth-message]')) el.textContent = message;
  if(status) status.textContent = message;
  if(tabs.length) select(tabs[0].dataset.authTab);
})();
