/* Vainah VPN account preview. Public Render API only: no fake sessions. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const write = (id, value) => { const element = $(id); if(element) element.textContent = value; };
  const hide = (id, yes) => { const element = $(id); if(element) element.hidden = yes; };

  hide('account-auth-panel', false);
  hide('account-private', true);
  hide('account-alt-private', true);
  hide('account-exit', true);
  hide('account-open-vpn', true);
  hide('account-copy-vpn', true);
  write('account-user', 'Гость');
  write('account-avatar', 'V');
  write('account-auth-status', 'Вход ещё не подключён к Python API на Render.');
  const getVpn = $('account-get-vpn');
  if(getVpn) getVpn.disabled = true;
  const refresh = $('account-refresh');
  if(refresh) refresh.disabled = true;

  async function publicStatus() {
    try {
      const [statusResponse, overviewResponse] = await Promise.all([
        fetch('/api/site/services', {headers: {Accept: 'application/json'}, cache: 'no-store'}),
        fetch('/api/v1/overview', {headers: {Accept: 'application/json'}, cache: 'no-store'})
      ]);
      if(!statusResponse.ok || !overviewResponse.ok) throw Error('UNAVAILABLE');
      const status = await statusResponse.json();
      const overview = await overviewResponse.json();
      const accountConnected = overview.account?.state === 'connected';
      // Do not fabricate a login from public status fields.
      write('account-auth-status', accountConnected
        ? 'Сервис аккаунтов настроен, но защищённый вход на этой странице ещё не реализован.'
        : 'Вход в аккаунт пока не подключён к серверу Render. Покупки и подписки здесь не показываются.');
      const h1 = status.services?.h1;
      write('account-h1-state', h1?.message || 'Проверка H1Cloud пока недоступна.');
    } catch {
      write('account-auth-status', 'Не удалось проверить состояние входа на Render. Попробуй позже.');
      write('account-h1-state', 'Проверка H1Cloud недоступна.');
    }
  }
  if(refresh) refresh.addEventListener('click', publicStatus);
  window.onVainahAccountAuth = () => {
    write('account-auth-status', 'Авторизация недоступна до подключения защищённых серверных сессий.');
  };
  window.onVainahAltLogin = window.onVainahAccountAuth;
  void publicStatus();
})();
