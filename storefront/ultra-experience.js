/* Vainah Ultra Experience — UI only. Never reads authentication, payment or VPN secrets.
   Preferences store solely theme + layout density in localStorage. */
(() => {
  'use strict';
  if (!document.body || document.getElementById('vx-ultra-ribbon')) return;
  const THEMES = Object.freeze({
    aurora: ['Лесной свет', 'Лайм и глубокий зелёный'],
    ocean: ['Океан', 'Синий и бирюзовый'],
    graphite: ['Графит', 'Строгий тёмный'],
    sunset: ['Закат', 'Тёплый коралловый'],
    midnight: ['Полночь', 'Глубокий индиго'],
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
    ['compare.html', 'Сравнение'],
    ['assistant.html', 'Подбор тарифа'],
    ['device-center.html', 'Подключение'],
    ['whats-new.html', 'Что нового'],
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
  let settings = { theme: 'aurora', density: 'normal', textSize: 'standard', motion: 'system' };
  try {
    const raw = localStorage.getItem(storageKey);
    if (raw && raw.length < 200) {
      const parsed = JSON.parse(raw);
      if (Object.hasOwn(THEMES, parsed.theme)) settings.theme = parsed.theme;
      if (parsed.density === 'normal' || parsed.density === 'compact')
        settings.density = parsed.density;
      if (parsed.textSize === 'standard' || parsed.textSize === 'large')
        settings.textSize = parsed.textSize;
      if (parsed.motion === 'system' || parsed.motion === 'reduce')
        settings.motion = parsed.motion;
    }
  } catch { /* private mode / blocked storage: use safe defaults */ }
  function apply() {
    document.documentElement.dataset.vxTheme = settings.theme;
    document.documentElement.dataset.vxDensity = settings.density;
    document.documentElement.dataset.vxTextSize = settings.textSize;
    document.documentElement.dataset.vxMotion = settings.motion;
    const themeTag = document.querySelector('meta[name="theme-color"]');
    if (themeTag) themeTag.setAttribute('content', {
      ocean:'#081e34',graphite:'#0b1520',sunset:'#281b2c',
      midnight:'#101126',aurora:'#101612'
    }[settings.theme]);
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
    ['whats-new.html', 'Новое'],
  ]) {
    const link = create('a', title, 'vx-ultra-action');
    link.href = path;
    if (pathname === path) {
      link.setAttribute('aria-current', 'page');
    }
    actions.append(link);
  }
  const settingsButton = create('button', '⚙ Настроить', 'vx-ultra-settings');
  settingsButton.type = 'button';
  settingsButton.setAttribute('aria-haspopup', 'dialog');
  settingsButton.setAttribute('aria-label', 'Настроить оформление Vainah VPN');
  actions.append(settingsButton);
  ribbon.append(identity, actions);
  // The home page hides the duplicate ribbon; keep its settings reachable.
  const homeActions = document.querySelector('[data-refresh-home] .refresh-more');
  if (homeActions) homeActions.append(settingsButton);

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

  const accessibility = create('fieldset', null, 'vx-ultra-accessibility');
  accessibility.append(create('legend', 'Удобство чтения'));
  const largeText = create('label', null, 'vx-ultra-compact');
  const largeTextInput = create('input');
  largeTextInput.type = 'checkbox';
  largeTextInput.checked = settings.textSize === 'large';
  largeTextInput.addEventListener('change', () => {
    settings.textSize = largeTextInput.checked ? 'large' : 'standard';
    persist();
  });
  largeText.append(largeTextInput, create('span', 'Увеличить текст и элементы управления'));
  accessibility.append(largeText);
  const reducedMotion = create('label', null, 'vx-ultra-compact');
  const reducedMotionInput = create('input');
  reducedMotionInput.type = 'checkbox';
  reducedMotionInput.checked = settings.motion === 'reduce';
  reducedMotionInput.addEventListener('change', () => {
    settings.motion = reducedMotionInput.checked ? 'reduce' : 'system';
    persist();
  });
  reducedMotion.append(reducedMotionInput, create('span', 'Уменьшить анимации и эффекты'));
  accessibility.append(reducedMotion);
  const reset = create('button', 'Вернуть настройки по умолчанию', 'vx-ultra-reset');
  reset.type = 'button';
  reset.addEventListener('click', () => {
    settings = {theme:'aurora', density:'normal', textSize:'standard', motion:'system'};
    compactInput.checked = false;
    largeTextInput.checked = false;
    reducedMotionInput.checked = false;
    persist();
    updateButtons();
  });
  accessibility.append(reset);
  body.append(accessibility);
  const quick = create('div', null, 'vx-ultra-links');
  quick.append(create('strong', 'Быстрые переходы'));
  for (const [path, title] of safePages) {
    const a = create('a', title, '');
    a.href = path;
    quick.append(a);
  }
  body.append(quick);

  // Explicit read-only diagnostics. Never interpret API health as a live
  // VPN tunnel or a confirmed customer payment. No automatic polling.
  const diagnostics = create('section', null, 'vx-ultra-health');
  diagnostics.append(create('strong', 'Проверка сервисов'),
    create('p', 'Проверка веб-API не подтверждает работу VPN-туннеля или возможность оплаты.', 'vx-ultra-help'));
  const check = create('button', 'Проверить сейчас', 'vx-ultra-health-button');
  check.type = 'button';
  const results = create('div', '', 'vx-ultra-health-results');
  results.setAttribute('role', 'status');
  results.setAttribute('aria-live', 'polite');
  check.addEventListener('click', async () => {
    if (check.disabled) return;
    check.disabled = true;
    results.replaceChildren(create('p', 'Проверяем веб-сервисы…'));
    // The static site does not host authenticated APIs; never mislabel
    // an absent static route as a payment or VPN outage.
    if (location.hostname === 'vainahvpn.onrender.com') {
      results.replaceChildren(create('p',
        'Статусы API проверяются на backend-домене, а не на статическом сайте.'));
      const link = create('a', 'Открыть технический статус ↗');
      link.href = 'https://vainahvpn-python-preview.onrender.com/status.html';
      link.rel = 'noopener';
      results.append(link);
      check.disabled = false;
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch('/api/site/services', {
        method:'GET',credentials:'same-origin',cache:'no-store',redirect:'error',
        headers:{Accept:'application/json'},signal:controller.signal,
      });
      if (!response.ok) throw Error('STATUS_UNAVAILABLE');
      const data = await response.json();
      const list = data?.services;
      if (!list || typeof list !== 'object') throw Error('STATUS_INVALID');
      results.replaceChildren();
      for (const [key, label] of [
        ['database','PostgreSQL'],
        ['h1','H1Cloud API'],
        ['rollypay','RollyPay API'],
        ['webhook','Подписанные webhook'],
      ]) {
        const status = list[key]?.status;
        let detail = 'Нет подтверждённых данных';
        if (key === 'webhook') {
          if (status === 'verified') detail = 'Есть подтверждённая история оплаты и выдачи VPN';
          else if (status === 'received') detail = 'Webhook об оплате получен; выдача здесь не подтверждена';
          else if (status === 'configured') detail = 'Подпись настроена; факт доставки не подтверждён этой проверкой';
          else if (status === 'not_connected') detail = 'Подпись webhook не настроена';
        } else if (status === 'ok') {
          detail = 'API отвечает; это не проверка VPN-туннеля или новой покупки';
        } else if (status === 'unavailable') {
          detail = 'Связь при проверке не подтверждена';
        } else if (status === 'not_connected') {
          detail = 'Не настроено';
        }
        const line = create('p', label + ': ' + detail);
        line.dataset.state = status === 'ok' || (key === 'webhook' && status === 'verified')
          ? 'configured' : 'unknown';
        results.append(line);
      }
    } catch {
      results.replaceChildren(create('p',
        'Не удалось получить ответ веб-API. Доступность VPN и оплаты остаётся неизвестной.'));
    } finally {
      clearTimeout(timer);
      check.disabled = false;
    }
  });
  diagnostics.append(check, results);
  body.append(diagnostics);
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
    largeTextInput.checked = settings.textSize === 'large';
    reducedMotionInput.checked = settings.motion === 'reduce';
    if (!dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
    }
  }
  settingsButton.addEventListener('click', openSettings);
  // Clicking the native dialog backdrop closes it, without affecting checkout.
  dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close?.();
  });
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
