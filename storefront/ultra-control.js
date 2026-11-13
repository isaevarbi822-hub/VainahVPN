/* Vainah Ultra Control: client-only route guidance, no identity/payment/API operations. */
(() => {
  'use strict';
  if (!document.body || document.getElementById('vx-control-open')) return;
  const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const journeys = Object.freeze({
    connect: {
      title: 'Подключить VPN',
      description: 'Выбери устройство, затем открой подходящую инструкцию.',
      steps: [
        ['Выбрать устройство', 'Открой инструкцию именно для своей платформы.'],
        ['Получить подписку', 'Войди в кабинет и проверь свою VPN-ссылку.'],
        ['Импортировать профиль', 'Скопируй или открой конфигурацию в совместимом клиенте.'],
      ],
    },
    account: {
      title: 'Моя подписка',
      description: 'Управление доступом всегда выполняется после входа в кабинет.',
      links: [
        ['account.html', 'Открыть личный кабинет', 'Подписка, VPN-ссылка, история заказов'],
        ['my-devices.html', 'Мои устройства', 'Зарегистрированные устройства и помощь'],
        ['notifications.html', 'Уведомления', 'Срок подписки и напоминания'],
        ['plans.html', 'Тарифы', 'Посмотреть варианты перед оформлением'],
      ],
    },
    support: {
      title: 'Исправить проблему',
      description: 'Начни с диагностики. Никаких изменений в подписке здесь не происходит.',
      links: [
        ['connection-check.html', 'Проверка подключения', 'Если VPN не соединяется'],
        ['browser-check.html', 'Проверка браузера', 'Если кнопки и страницы не работают'],
        ['network-check.html', 'Проверка сети', 'Если сайт или API недоступны'],
        ['repair-wizard.html', 'Мастер решения ошибок', 'Пошаговый поиск причины'],
        ['support-center.html', 'Поддержка', 'Создать обращение после входа'],
      ],
    },
    explore: {
      title: 'Исследовать Vainah VPN',
      description: 'Полезные разделы и возможности на одной панели.',
      links: [
        ['features.html', 'Возможности', 'Функции и преимущества сервиса'],
        ['compare.html', 'Сравнение тарифов', 'Сроки, устройства и стоимость'],
        ['speed.html', 'Тест скорости', 'Проверка скорости интернета в браузере'],
        ['status.html', 'Статус сервисов', 'Безопасная диагностика доступности веб-систем'],
        ['whats-new.html', 'Последние изменения', 'Обновления интерфейса и функций'],
      ],
    },
  });
  const devices = Object.freeze([
    ['android', 'Android', 'Смартфон или планшет'],
    ['ios', 'iPhone и iPad', 'iOS / iPadOS'],
    ['windows', 'Windows', 'ПК или ноутбук'],
    ['macos', 'Mac', 'macOS'],
    ['linux', 'Linux', 'Компьютер'],
  ]);
  const launcher = make('button', 'vx-control-launch', '✦ Помощник Vainah');
  launcher.type = 'button';
  launcher.id = 'vx-control-open';
  launcher.setAttribute('aria-haspopup', 'dialog');
  launcher.setAttribute('aria-controls', 'vx-control-dialog');
  launcher.setAttribute('aria-label', 'Открыть центр действий Vainah VPN');
  const rail = document.querySelector('.vx-utility-rail');
  if (rail) {
    launcher.classList.add('vx-control-launch-rail');
    rail.append(launcher);
  } else {
    const header = document.querySelector('body > header,body > .site-header');
    if (header) header.after(launcher);
    else document.body.prepend(launcher);
  }
  const dialog = make('dialog', 'vx-control-dialog');
  dialog.id = 'vx-control-dialog';
  dialog.setAttribute('aria-labelledby', 'vx-control-title');
  dialog.setAttribute('aria-describedby', 'vx-control-description');
  const panel = make('div', 'vx-control-panel');
  const head = make('div', 'vx-control-head');
  const heading = make('div');
  heading.append(make('span', 'vx-control-kicker', 'VAINAH VPN / ЦЕНТР ДЕЙСТВИЙ'));
  const h2 = make('h2', '', 'Что хочешь сделать?');
  h2.id = 'vx-control-title';
  heading.append(h2);
  const close = make('button', 'vx-control-close', '✕');
  close.type = 'button';
  close.setAttribute('aria-label', 'Закрыть центр действий');
  close.addEventListener('click', () => dialog.close());
  head.append(heading, close);
  const intro = make('p', 'vx-control-intro',
    'Выбери задачу — помощник покажет нужный раздел, без лишних шагов и опасных действий.');
  intro.id = 'vx-control-description';
  const tabs = make('div', 'vx-control-tabs');
  tabs.setAttribute('role', 'tablist');
  tabs.setAttribute('aria-label', 'Выбор задачи');
  const tabsData = [
    ['connect','Подключить'],
    ['account','Мой VPN'],
    ['support','Помощь'],
    ['explore','Возможности'],
  ];
  let active = 'connect';
  const content = make('div', 'vx-control-content');
  const tabButtons = new Map();
  function createLink(href, title, subtitle) {
    const link = make('a', 'vx-control-card');
    link.href = href;
    const titleEl = make('strong', '', title);
    const info = make('small', '', subtitle);
    const arrow = make('span', 'vx-control-arrow', '↗');
    arrow.setAttribute('aria-hidden', 'true');
    link.append(titleEl, info, arrow);
    return link;
  }
  function render() {
    const selected = journeys[active];
    for (const [key, button] of tabButtons) {
      const isCurrent = key === active;
      button.setAttribute('aria-selected', String(isCurrent));
      button.tabIndex = isCurrent ? 0 : -1;
    }
    content.replaceChildren();
    content.append(make('h3', '', selected.title),
      make('p', 'vx-control-description', selected.description));
    if (active === 'connect') {
      const grid = make('div', 'vx-control-devices');
      for (const [code, name, subtitle] of devices) {
        grid.append(createLink('connect.html?device=' + code, name, subtitle));
      }
      const steps = make('ol', 'vx-control-steps');
      selected.steps.forEach(([name, explanation]) => {
        const li = make('li');
        li.append(make('strong', '', name), make('span', '', explanation));
        steps.append(li);
      });
      content.append(grid, steps);
      const manage = createLink('account.html',
        'Есть подписка? Открой личный кабинет', 'Проверить свой доступ после авторизации');
      manage.classList.add('vx-control-main-link');
      content.append(manage);
    } else {
      const grid = make('div', 'vx-control-links');
      for (const [href, title, subtitle] of selected.links)
        grid.append(createLink(href, title, subtitle));
      content.append(grid);
    }
  }
  for (const [id, text] of tabsData) {
    const tab = make('button', 'vx-control-tab', text);
    tab.type = 'button';
    tab.id = 'vx-control-tab-' + id;
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', 'vx-control-content');
    tab.addEventListener('click', () => { active = id; render(); });
    tab.addEventListener('keydown', event => {
      if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
      event.preventDefault();
      const index = tabsData.findIndex(([key]) => key === id);
      const next = tabsData[(index + (event.key === 'ArrowRight' ? 1 : -1) + tabsData.length) % tabsData.length][0];
      active = next;
      render();
      tabButtons.get(next).focus();
    });
    tabs.append(tab);
    tabButtons.set(id, tab);
  }
  content.id = 'vx-control-content';
  content.setAttribute('role', 'tabpanel');
  const foot = make('p', 'vx-control-foot',
    'Помощник открывает только страницы сайта. Он не создаёт платежей и не меняет учётную запись.');
  panel.append(head, intro, tabs, content, foot);
  dialog.append(panel);
  document.body.append(dialog);
  function open() {
    active = 'connect';
    render();
    if (!dialog.open) dialog.showModal();
    tabButtons.get(active).focus();
  }
  launcher.addEventListener('click', open);
  dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener('close', () => launcher.focus());
  render();
})();