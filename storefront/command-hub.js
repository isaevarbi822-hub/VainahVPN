/* Vainah Control: public-only GET diagnostics, local UI state, no payment actions. */
(() => {
  'use strict';
  const $ = (selector, root = document) => root.querySelector(selector);
  // Vainah chat is a locally guided help tab provided by the shared site shell.
  document.querySelector('#vx-hub-open-chat')?.addEventListener('click',()=>{
    document.querySelector('#vx-control-open')?.click();
  });

  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const search = $('#vx-hub-search');
  const featureCards = $$('#vx-hub-features a');
  const count = $('#vx-hub-search-count');
  const empty = $('#vx-hub-empty');
  const normalize = value => String(value || '').toLocaleLowerCase('ru')
    .replace(/ё/g, 'е').replace(/айфон/g, 'iphone')
    .replace(/айпад/g, 'ipad').replace(/андроид/g, 'android')
    .replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  if (search && featureCards.length) {
    const render = () => {
      const words = normalize(search.value).split(/\s+/).filter(Boolean);
      let shown = 0;
      featureCards.forEach(card => {
        const combined = normalize([
          card.dataset.terms, card.textContent,
        ].join(' '));
        const match = words.every(word => combined.includes(word));
        card.hidden = !match;
        if (match) shown += 1;
      });
      count.textContent = words.length
        ? 'Найдено разделов: ' + shown : 'Все разделы: ' + featureCards.length;
      empty.hidden = shown !== 0;
    };
    search.addEventListener('input', render);
    $('#vx-hub-clear')?.addEventListener('click', () => {
      search.value = ''; render(); search.focus();
    });
    render();
  }

  const devices = Object.freeze({
    android: ['Открой личный кабинет и найди свою подписку.', 'Установи совместимый VPN-клиент из доверенного источника.', 'Импортируй конфигурацию и проверь подключение в самом клиенте.'],
    ios: ['Получи личную ссылку после входа в кабинет.', 'Открой совместимый VPN-клиент на iPhone или iPad.', 'Импортируй профиль и разреши создание VPN-подключения в настройках устройства.'],
    windows: ['Открой кабинет и получи подписку.', 'Установи совместимый VPN-клиент для Windows.', 'Импортируй профиль и отдельно проверь, работает ли VPN-туннель.'],
    mac: ['Получи личную подписку в кабинете.', 'Установи совместимый VPN-клиент на macOS.', 'Импортируй профиль и проверь доступ в интернет через VPN.'],
  });
  const deviceButtons = $$('[data-vx-device]');
  const steps = $('#vx-hub-steps');
  const storedPlatform = (() => {
    try { return localStorage.getItem('vainah_ui_device'); } catch (_) { return null; }
  })();
  const setDevice = platform => {
    if (!devices[platform] || !steps) return;
    deviceButtons.forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.vxDevice === platform));
    });
    const list = document.createElement('ol');
    devices[platform].forEach(step => {
      const item = document.createElement('li');
      item.textContent = step;
      list.append(item);
    });
    steps.replaceChildren(list);
    try { localStorage.setItem('vainah_ui_device', platform); } catch (_) {}
  };
  deviceButtons.forEach(button => button.addEventListener('click', () => setDevice(button.dataset.vxDevice)));
  if (steps) setDevice(devices[storedPlatform] ? storedPlatform : 'android');

  const term = $('#vx-plan-term');
  const deviceCount = $('#vx-plan-devices');
  const planResult = $('#vx-hub-recommendation');
  function renderPlan() {
    if (!term || !deviceCount || !planResult) return;
    const family = deviceCount.value === '6';
    const termLabels = Object.freeze({
      short: 'короткий срок', month: '1 месяц',
      long: 'несколько месяцев', year: '1 год',
    });
    const name = family ? 'Семейные тарифы' : 'Личные тарифы';
    const intro = document.createElement('strong');
    intro.textContent = name;
    const description = document.createElement('p');
    description.textContent = 'Подбор: ' + termLabels[term.value] +
      ' · до ' + (family ? '6' : '3') + ' устройств. Доступные варианты и окончательные цены смотри в каталоге.';
    planResult.replaceChildren(intro, description);
  }
  term?.addEventListener('change', renderPlan);
  deviceCount?.addEventListener('change', renderPlan);
  renderPlan();

  const browserStatus = $('#vx-browser-status');
  const apiStatus = $('#vx-api-status');
  const checkoutStatus = $('#vx-checkout-status');
  const note = $('#vx-hub-status-note');
  const button = $('#vx-hub-check');
  const backendOrigin = 'https://vainahvpn-python-preview.onrender.com';
  const publicOrigins = ['https://vainahvpn.online','https://www.vainahvpn.online',
    'https://vainahvpn.onrender.com'];
  const isPublicSite=publicOrigins.includes(window.location.origin);
  const setStatus = (node, message, state) => {
    if (!node) return;
    node.textContent = message; node.dataset.state = state;
  };
  function refreshBrowserStatus() {
    setStatus(browserStatus, navigator.onLine ? 'Браузер сообщает: в сети' : 'Браузер сообщает: офлайн',
      navigator.onLine ? 'ok' : 'unknown');
  }
  window.addEventListener('online', refreshBrowserStatus);
  window.addEventListener('offline', refreshBrowserStatus);
  refreshBrowserStatus();

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  async function safeGet(path) {
    const url = (isPublicSite ? backendOrigin : '') + path;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      if (attempt) await sleep(2500);
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 18000);
      try {
        const response = await fetch(url, {
          method: 'GET', credentials: 'omit', cache: 'no-store',
          mode: 'cors', signal: controller.signal,
        });
        clearTimeout(timer);
        if (response.ok) return response;
      } catch (_) {
        clearTimeout(timer);
      }
    }
    return null;
  }
  async function runCheck() {
    if (!button || button.disabled) return;
    button.disabled = true;
    button.textContent = 'Проверяем…';
    setStatus(apiStatus, 'Запрос…', 'unknown');
    setStatus(checkoutStatus, 'Запрос…', 'unknown');
    try {
      if (!navigator.onLine) {
        setStatus(apiStatus, 'Нет подключения у браузера', 'unknown');
        setStatus(checkoutStatus, 'Не проверено', 'unknown');
        return;
      }
      // Only the public tariff GET route is CORS-readable by the marketing
      // origin. /api/health and /api/shop/config are deliberately same-origin.
      // Never report a CORS denial as a service outage.
      const health = await safeGet(isPublicSite?'/api/site/tariffs':'/api/health');
      let apiConfirmed=false;
      if(health){
        try{
          const data=await health.json();
          apiConfirmed=isPublicSite
            ? data.total===13&&Array.isArray(data.plans)&&data.plans.length===13
            : data&&typeof data==='object'&&!Array.isArray(data);
        }catch(_){apiConfirmed=false;}
      }
      setStatus(apiStatus,apiConfirmed
        ?(isPublicSite?'Публичный каталог API отвечает':'Служебное API отвечает')
        :'Не удалось подтвердить ответ API',apiConfirmed?'ok':'unknown');
      if(isPublicSite){
        setStatus(checkoutStatus,'Проверка доступна на странице оформления','unknown');
        if(note)note.textContent='Каталог API проверен отдельно от оплаты. Актуальные способы оплаты указаны на странице оформления.';
        return;
      }
      const configResponse = await safeGet('/api/shop/config');
      let ready = null;
      if (configResponse) {
        try {
          const config = await configResponse.json();
          if (typeof config.checkout_ready === 'boolean') ready = config.checkout_ready;
        } catch (_) {}
      }
      if (ready === true) {
        setStatus(checkoutStatus, 'API: оформление разрешено', 'ok');
      } else if (ready === false) {
        setStatus(checkoutStatus, 'API: оформление сейчас закрыто', 'unknown');
      } else {
        setStatus(checkoutStatus, 'Статус не подтверждён', 'unknown');
      }
      if (note) {
        note.textContent = 'Ответ служебного API не доказывает, что VPN-туннель работает. checkout_ready — разрешение на создание счёта, но не подтверждение проведённой оплаты.';
      }
    } finally {
      button.disabled = false;
      button.textContent = 'Проверить ещё раз';
    }
  }
  button?.addEventListener('click', runCheck);
})();
