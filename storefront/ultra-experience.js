/* Vainah Ultra Experience — UI only. Never reads authentication, payment or VPN secrets.
   Preferences store solely theme + layout density in localStorage. */
(() => {
  'use strict';
  if (!document.body || document.getElementById('vx-ultra-ribbon')) return;
  const THEMES = Object.freeze({
    aurora: ['Северное сияние', 'Фиолетовый и бирюзовый'],
    ocean: ['Океан', 'Синий и бирюзовый'],
    graphite: ['Графит', 'Строгий тёмный'],
  });
  const storageKey = 'vainah-ultra-appearance-v1';
  const safePages = Object.freeze([
    ['index.html', 'Главная'],
    ['plans.html', 'Тарифы'],
    ['account.html', 'Мой VPN'],
    ['notifications.html', 'Уведомления'],
    ['gifts.html', 'Подарки'],
    ['support-center.html', 'Поддержка'],
    ['servers.html', 'Серверы'],
    ['hub.html', 'Центр управления'],
    ['checkout.html', 'Оформление'],
    ['diagnostics.html', 'Диагностика'],
    ['referrals.html', 'Приглашения'],
  ]);
  const pathname = location.pathname.split('/').pop() || 'index.html';
  const section = safePages.find(item => item[0] === pathname);
  const create = (tag, text, klass) => {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (klass) node.className = klass;
    return node;
  };
  let settings = { theme: 'aurora', density: 'normal' };
  try {
    const raw = localStorage.getItem(storageKey);
    if (raw && raw.length < 200) {
      const parsed = JSON.parse(raw);
      if (Object.hasOwn(THEMES, parsed.theme)) settings.theme = parsed.theme;
      if (parsed.density === 'normal' || parsed.density === 'compact')
        settings.density = parsed.density;
    }
  } catch { /* private mode / blocked storage: use safe defaults */ }
  function apply() {
    document.documentElement.dataset.vxTheme = settings.theme;
    document.documentElement.dataset.vxDensity = settings.density;
    const themeTag = document.querySelector('meta[name="theme-color"]');
    if (themeTag) themeTag.setAttribute('content', settings.theme === 'ocean'
      ? '#081e34' : settings.theme === 'graphite' ? '#0b1520' : '#111027');
  }
  function persist() {
    apply();
    try { localStorage.setItem(storageKey, JSON.stringify(settings)); }
    catch { /* no storage required */ }
  }
  apply();

  const ribbon = create('nav', null, 'vx-ultra-ribbon');
  ribbon.id = 'vx-ultra-ribbon';
  ribbon.setAttribute('aria-label', 'Быстрые действия Vainah VPN');
  const identity = create('div', null, 'vx-ultra-identity');
  identity.append(create('span', '✦ VAINAH', 'vx-ultra-brand'),
    create('span', section?.[1] || 'Твоё соединение', 'vx-ultra-location'));
  const actions = create('div', null, 'vx-ultra-actions');
  for (const [path, title] of [
    ['plans.html', 'Тарифы'],
    ['account.html', 'Мой VPN'],
    ['notifications.html', 'Уведомления'],
    ['support-center.html', 'Поддержка'],
  ]) {
    const link = create('a', title, 'vx-ultra-action');
    link.href = path;
    if (pathname === path) {
      link.setAttribute('aria-current', 'page');
    }
    actions.append(link);
  }
  const settingsButton = create('button', '⚙ Вид', 'vx-ultra-settings');
  settingsButton.type = 'button';
  settingsButton.setAttribute('aria-haspopup', 'dialog');
  settingsButton.setAttribute('aria-label', 'Настроить оформление Vainah VPN');
  actions.append(settingsButton);
  ribbon.append(identity, actions);

  const header = document.querySelector('body > header, body > .site-header');
  const rail = document.querySelector('.vx-utility-rail');
  if (rail) rail.after(ribbon);
  else if (header) header.after(ribbon);
  else document.body.prepend(ribbon);

  const dialog = create('dialog', null, 'vx-ultra-dialog');
  dialog.setAttribute('aria-labelledby', 'vx-ultra-title');
  const body = create('div', null, 'vx-ultra-dialog-body');
  const top = create('div', null, 'vx-ultra-dialog-heading');
  const heading = create('div');
  heading.append(create('span', 'VAINAH VPN / ПЕРСОНАЛИЗАЦИЯ', 'vx-ultra-kicker'),
    create('h2', 'Настрой внешний вид', ''));
  const close = create('button', '✕', 'vx-ultra-close');
  close.type = 'button';
  close.setAttribute('aria-label', 'Закрыть настройки');
  close.addEventListener('click', () => dialog.close?.());
  top.append(heading, close);
  body.append(top, create('p',
    'Эти настройки меняют только оформление браузера. Подписка, платежи и VPN остаются без изменений.',
    'vx-ultra-help'));

  const themes = create('fieldset', null, 'vx-ultra-options');
  themes.append(create('legend', 'Цветовая тема'));
  const buttons = new Map();
  for (const [key, [name, description]] of Object.entries(THEMES)) {
    const button = create('button', null, 'vx-ultra-theme vx-ultra-theme-'+key);
    button.type = 'button';
    button.dataset.theme = key;
    button.append(create('span', null, 'vx-ultra-swatch'),
      create('strong', name), create('small', description));
    button.addEventListener('click', () => {
      settings.theme = key;
      persist();
      updateButtons();
    });
    themes.append(button);
    buttons.set(key, button);
  }
  body.append(themes);
  const compact = create('label', null, 'vx-ultra-compact');
  const compactInput = create('input');
  compactInput.type = 'checkbox';
  compactInput.checked = settings.density === 'compact';
  compactInput.addEventListener('change', () => {
    settings.density = compactInput.checked ? 'compact' : 'normal';
    persist();
  });
  compact.append(compactInput, create('span', 'Компактное расположение карточек'));
  body.append(compact);
  const quick = create('div', null, 'vx-ultra-links');
  quick.append(create('strong', 'Быстрые переходы'));
  for (const [path, title] of safePages) {
    const a = create('a', title, '');
    a.href = path;
    quick.append(a);
  }
  body.append(quick);
  dialog.append(body);
  document.body.append(dialog);
  function updateButtons() {
    for (const [key, button] of buttons) {
      button.setAttribute('aria-pressed', String(key === settings.theme));
    }
  }
  updateButtons();
  function openSettings() {
    updateButtons();
    compactInput.checked = settings.density === 'compact';
    if (!dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
    }
  }
  settingsButton.addEventListener('click', openSettings);
  // Keyboard shortcut only when not typing; Ctrl+K is already site search.
  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.shiftKey &&
        event.key.toLowerCase() === 'u') {
      event.preventDefault();
      if (dialog.open) dialog.close?.();
      else openSettings();
    }
  });
})();
