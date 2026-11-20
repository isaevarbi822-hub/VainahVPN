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
  // Support replies are local guides. Nothing typed in chat is sent to a server.
  const replies = Object.freeze([
    {pattern:/оплат|платеж|роллипей|rollypay|касс|чек|квитанц|вернул|возврат/i,
     answer:'Оплата проходит на защищённой странице RollyPay. Если деньги списались, не оплачивай повторно: открой историю заказов в кабинете или обратись в поддержку.',
     links:[['account.html','Мои заказы'],['support-center.html','Поддержка']]},
    {pattern:/тариф|цен|руб|сколько стоит|семь|семья|подписк/i,
     answer:'В каталоге есть варианты по сроку и числу устройств. Цена и возможность покупки подтверждаются сервером перед оформлением; новые концепты не продаются.',
     links:[['plans.html','Все тарифы'],['compare.html','Сравнение']]},
    {pattern:/android|андроид|samsung|самсунг|телефон/i,
     answer:'На Android открой свою подписку в кабинете, импортируй её в совместимый VPN-клиент и проверь подключение в самом приложении.',
     links:[['connect.html?device=android','Мастер Android']]},
    {pattern:/ipad|iphone|ios|айпад|айфон|apple/i,
     answer:'Для iPhone и iPad нужен совместимый VPN-клиент. Открой инструкции, затем импортируй личную подписку после входа.',
     links:[['connect.html?device=ios','Настройка iOS']]},
    {pattern:/windows|виндовс|компьютер|пк|ноутбук/i,
     answer:'На Windows VPN-туннель создаёт установленный клиент, а не сайт. Выбери подходящий клиент и импортируй подписку.',
     links:[['connect.html?device=windows','Настройка Windows']]},
    {pattern:/macos|macbook|mac|макбук|макос/i,
     answer:'Для macOS открой мастер подключения и импортируй личную конфигурацию в совместимый клиент.',
     links:[['connect.html?device=macos','Настройка Mac']]},
    {pattern:/подар|gift|код|сертификат/i,
     answer:'Подарочные коды и подписки открываются в личном кабинете. Не публикуй полученный код в чате.',
     links:[['gifts.html','Подарочные карты']]},
    {pattern:/email|почт|код вход|не приходит|telegram|телеграм|google|гугл|вход|аккаунт/i,
     answer:'Проверь адрес почты и папку «Спам». Если вход через Telegram или Google не открывается, попробуй email-код и обратись в поддержку.',
     links:[['account.html','Войти'],['support-center.html','Поддержка']]},
    {pattern:/ошиб|403|не работает|сбой|подключ|сервер|пинг|скорост|интернет/i,
     answer:'Начни с центра диагностики и мастера решения проблем. Статус сайта не подтверждает состояние VPN-туннеля.',
     links:[['diagnostics.html','Диагностика'],['repair-wizard.html','Мастер решения проблем']]},
    {pattern:/пробн|бесплат|демо|тест/i,
     answer:'Пробный доступ и правила его активации указаны на сервере. Перейди на страницу пробного периода и проверь условия.',
     links:[['trial.html','Пробный доступ']]},
  ]);
  const chatHistory = [];
  let chatDraft = '';
  function getResponse(message) {
    const rule = replies.find(item => item.pattern.test(message));
    return rule || {
      answer:'Я пока помогаю по правилам и инструкциям, а не через подключённую AI-модель. Спроси про тарифы, вход, оплату, подключение, серверы или ошибки. Для личного вопроса используй поддержку.',
      links:[['help.html','Вопросы и ответы'],['support-center.html','Поддержка']],
    };
  }
  function renderChat() {
    content.append(make('h3','','Чат с Vainah'),make('p','vx-control-description',
      'Интерактивный справочный чат. Ответы основаны на готовых инструкциях; это не оператор и не генеративный ИИ. Не отправляй пароли и VPN-ключи.'));
    const log = make('div','vx-chat-log');
    log.setAttribute('role','log');log.setAttribute('aria-live','polite');log.setAttribute('aria-label','Переписка с помощником');
    const addMessage=(text,who,links=[])=>{
      const item=make('div','vx-chat-message vx-chat-'+who);
      item.append(make('strong','',who==='user'?'Ты':'Vainah'),make('p','',text));
      if(links.length){
        const actions=make('div','vx-chat-actions');
        links.forEach(([url,label])=>actions.append(createLink(url,label,'')));
        item.append(actions);
      }
      log.append(item);
    };
    if(!chatHistory.length)addMessage('Привет! Помогу с тарифами, подключением, входом, оплатой и ошибками. Выбери подсказку или напиши вопрос.','bot');
    chatHistory.forEach(({who,text,links})=>addMessage(text,who,links));
    const suggestions=make('div','vx-chat-suggestions');
    ['Как подключить VPN?','Какой тариф выбрать?','Оплата не работает','Не приходит код'].forEach(label=>{
      const button=make('button','',label);button.type='button';
      button.addEventListener('click',()=>send(label));
      suggestions.append(button);
    });
    const form=make('form','vx-chat-form');
    const label=make('label','','Твой вопрос');label.htmlFor='vx-chat-input';
    const input=make('input','');input.id='vx-chat-input';input.name='message';
    input.placeholder='Например: как подключить на iPad?';input.maxLength=350;
    input.setAttribute('autocomplete','off');input.value=chatDraft;
    input.addEventListener('input',()=>{chatDraft=input.value;});
    const submit=make('button','','Отправить');submit.type='submit';
    const clear=make('button','vx-chat-clear','Очистить чат');clear.type='button';
    clear.addEventListener('click',()=>{chatHistory.length=0;chatDraft='';render();});
    form.append(label,input,submit,clear);
    const send=text=>{
      const value=String(text||'').trim().slice(0,350);
      if(!value)return;
      chatHistory.push({who:'user',text:value,links:[]});
      const reply=getResponse(value);
      chatHistory.push({who:'bot',text:reply.answer,links:reply.links});
      if(chatHistory.length>24)chatHistory.splice(0,chatHistory.length-24);
      chatDraft='';render();const updated=content.querySelector('.vx-chat-log');
      if(updated)updated.scrollTop=updated.scrollHeight;
      content.querySelector('#vx-chat-input')?.focus();
    };
    form.addEventListener('submit',event=>{event.preventDefault();send(input.value);});
    content.append(log,suggestions,form);
    log.scrollTop=log.scrollHeight;
  }
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
  launcher.setAttribute('aria-label', 'Открыть чат с помощником Vainah');
  // Floating launcher stays available even where a legacy navigation rail
  // is intentionally hidden on mobile or on the refreshed homepage.
  (document.querySelector('.vv-menu-tools') || document.body).append(launcher);
  const dialog = make('dialog', 'vx-control-dialog');
  dialog.id = 'vx-control-dialog';
  dialog.setAttribute('aria-labelledby', 'vx-control-title');
  dialog.setAttribute('aria-describedby', 'vx-control-description');
  const panel = make('div', 'vx-control-panel');
  const head = make('div', 'vx-control-head');
  const heading = make('div');
  heading.append(make('span', 'vx-control-kicker', 'VAINAH VPN / ЦЕНТР ДЕЙСТВИЙ'));
  const h2 = make('h2', '', 'Помощник Vainah');
  h2.id = 'vx-control-title';
  heading.append(h2);
  const close = make('button', 'vx-control-close', '✕');
  close.type = 'button';
  close.setAttribute('aria-label', 'Закрыть центр действий');
  close.addEventListener('click', () => dialog.close());
  head.append(heading, close);
  const intro = make('p', 'vx-control-intro',
    'Напиши вопрос или открой быстрые действия. Ответы — по базе подсказок; для личных вопросов доступна поддержка.');
  intro.id = 'vx-control-description';
  const tabs = make('div', 'vx-control-tabs');
  tabs.setAttribute('role', 'tablist');
  tabs.setAttribute('aria-label', 'Выбор задачи');
  const tabsData = [
    ['chat','Чат Vainah'],
    ['connect','Подключить'],
    ['account','Мой VPN'],
    ['support','Помощь'],
    ['explore','Возможности'],
  ];
  let active = 'chat';
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
    if(active==='chat'){renderChat();return;}
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
    'Справочный чат обрабатывается в браузере. Он не хранит историю на сервере, не создаёт оплат и не меняет аккаунт.');
  panel.append(head, intro, tabs, content, foot);
  dialog.append(panel);
  document.body.append(dialog);
  function open() {
    active = 'chat';
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