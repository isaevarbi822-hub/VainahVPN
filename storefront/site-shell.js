/* Vainah VPN shared site shell: no account data, no external calls, no payment actions. */
(function(){
  'use strict';
  // Public static pages live on the CDN; customer data and payments must stay
  // on the original same-origin Python backend. Do not proxy session cookies,
  // OAuth callbacks or payment requests through the static site.
  const staticOrigin='https://vainahvpn.onrender.com';
  const customOrigins=new Set(['https://vainahvpn.online','https://www.vainahvpn.online']);
  const accountOrigin='https://vainahvpn-python-preview.onrender.com';
  if(window.location.origin===staticOrigin||customOrigins.has(window.location.origin)){
    const currentOrigin=window.location.origin;
    // If the domain later moves from Render Static to Python, keep its
    // same-origin account and checkout pages instead of redirecting them away.
    const backendProbe=customOrigins.has(currentOrigin)
      ? import('./custom-origin-probe.mjs')
          .then(module=>module.isPythonBackend()).catch(()=>false)
      : Promise.resolve(false);
    const backendPages=new Set([
      '/account.html','/checkout.html','/trial.html',
      '/hub.html','/my-devices.html','/notifications.html',
      '/operator-grants.html','/referrals.html','/rewards.html',
      '/handoff.html',
      '/gifts.html','/gift-cards.html','/support-center.html',
      '/support-operator.html','/operator-pilot.html','/operations.html',
      '/payment-return.html','/checkout-return.html',
      '/network-check.html','/connection-monitor.html',
      '/status.html','/speed.html','/diagnostics.html',
      '/connection-check.html'
    ]);
    const toBackend=url=>accountOrigin+url.pathname+url.search+url.hash;
    const currentUrl=new URL(window.location.href);
    if(backendPages.has(currentUrl.pathname)||currentUrl.pathname.startsWith('/api/')){
      void backendProbe.then(isBackend=>{
        if(!isBackend)window.location.replace(toBackend(currentUrl));
      });
      return;
    }
    document.addEventListener('click',event=>{
      if(event.defaultPrevented||event.button!==0||
         event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
      const link=event.target.closest?.('a[href]');
      if(!link||link.target==='_blank'||link.hasAttribute('download'))return;
      const destination=new URL(link.href);
      if(destination.origin!==currentOrigin||
         !(backendPages.has(destination.pathname)||destination.pathname.startsWith('/api/')))return;
      event.preventDefault();
      void backendProbe.then(isBackend=>window.location.assign(
        isBackend?destination.href:toBackend(destination)
      ));
    },true);
    // Canonical tags are set in HTML for the key landing pages. Update
    // remaining pages during rendering as a secondary SEO consistency measure.
    const canonical=document.querySelector('link[rel="canonical"]');
    if(canonical&&canonical.href.startsWith(accountOrigin+'/')){
      canonical.href=currentOrigin+new URL(canonical.href).pathname;
    }
  }
  const pages=[
    ['index.html','Главная','Начало, новости сайта, навигация','главная'],
    ['command-hub.html','Vainah Control','Новый центр: поиск, устройства, подбор тарифов и публичная диагностика','центр главная новое функции dashboard живой'],
    ['hub.html','Центр управления','Подписки, подарки, напоминания, поддержка и статус сервисов','аккаунт управление сервисы центр'],
    ['whats-new.html','Что нового','Темы, личный кабинет, тарифы, устройства, подарки и обновления','обновление новые функции'],
    ['plans.html','75 платных тарифов','Поиск, сортировка и сравнение трёх планов; срок 2–730 дней','цены купить подписка тарифы mini sprint legend family ₽ 149'],
    ['trial.html','Пробный период · 0 ₽','1 день, 2 устройства и 10 ГБ бесплатно','пробник пробный бесплатно бесплатный тест 24 часа 10 гб'],
    ['compare.html','Сравнение тарифов','75 платных тарифов, цена за день, срок и число устройств','разница тарифов цена за день семейные'],
    ['assistant.html','Подобрать тариф','Помощник по сроку и количеству устройств','выбрать подобрать'],
    ['account.html','Личный кабинет','VPN, срок, заказы и история после входа по email','мой впн мой vpn продление телеграм'],
    ['checkout.html','Оформление на сайте','Выбор подписки, RollyPay и Platega','оплата роллипей platega платега касса'],
    ['device-center.html','Мастер подключения','Пошаговая настройка и чек-лист','установка устройство конфигурация'],
    ['connect.html','Vainah Connect','Интерактивный мастер подключения к VPN на всех устройствах','qr подключение андроид айфон мак линукс виндовс установка'],
    ['devices.html','Все устройства','iPhone, iPad, Android, Windows, macOS','телефон айфон планшет'],
    ['my-devices.html','Мои устройства','Личный список своих устройств; без отключения настоящего VPN','устройства имена телефон ноутбук планшет добавить удалить записи'],
    ['guide.html','Инструкция','Импорт VPN-конфигурации','настройка ключ'],
    ['start.html','Быстрый старт','С чего начать, если подписки нет','новичок'],
    ['status.html','Статус сервисов','H1Cloud, PostgreSQL, RollyPay, Platega и webhook','недоступность сбой'],
    ['speed.html','Тест HTTP-соединения','Примерная скорость обмена с Python-сервером Render, не скорость VPN-туннеля','speed скорость тест интернет замер загрузка отдача ping'],
    ['diagnostics.html','Центр диагностики','Проверки соединения и решения проблем','не работает ошибка'],
    ['ultra-repair.html','Vainah Repair Ultra','Интерактивные шаги решения проблем для пяти платформ','ремонт восстановить vpn ultra не подключается помощь ошибка wifi мобильная сеть'],
    ['troubleshooting.html','Решение проблем','Диагностика импорта, ошибок и соединения','помощь ошибка'],
    ['help.html','Ответы на вопросы','FAQ про подписку и подключение','частые вопросы'],
    ['library.html','Библиотека знаний','Поиск по материалам проекта','справочник статьи'],
    ['contact.html','Поддержка','Обращение в службу поддержки','связь написать'],
    ['support-center.html','Мои обращения','Список заявок, переписка с оператором, поддержка по аккаунту','заявка тикет поддержка служба помощи ответ'],
    ['notifications.html','Мои уведомления','Срок VPN, продление и настройки email-напоминаний','напоминание продлить 7 3 1 день срок письмо'],
    ['gifts.html','Подарочные карты','Подарочные подписки и полученные коды','подарок код дарить подарочная карта'],
    ['referrals.html','Приглашения','Программа приглашений и рекомендации','пригласить реферал ссылка'],
    ['servers.html','Серверы','Локации и доступность панели','локации страны'],
    ['security.html','Безопасность','Защита личной конфигурации','приватность'],
    ['privacy.html','Конфиденциальность','Как сайт обращается с данными','данные'],
    ['terms.html','Условия сервиса','Правила использования Vainah VPN','условия'],
    ['network-check.html','Проверка соединения','HTTPS, Python API, email-вход, оплата и отклик сервера','здоровье сети диагностика сеть health check ping'],
    ['network-toolkit.html','12 сетевых калькуляторов','Скорость, трафик, прогноз за месяц, лимит устройств и резервное копирование','калькулятор расчёт скорость Мбит скачать время трафик мегабайт'],
    ['connection-monitor.html','Монитор стабильности','Повторные замеры отклика API, ошибки и копирование отчёта','монитор интернет стабильно latency ping uptime стабильность'], 
    ['browser-check.html','Проверка браузера','Поддержка HTTPS, копирования и интерфейса','совместимость браузер смартфон проверка'], 
    ['repair-wizard.html','Мастер решения проблем','Пошаговые действия по устройству, оплате и VPN','помоги не работает почта импорт vpn'],
    ['tools.html','Все инструменты','Каталог функций, диагностики и настроек Vainah VPN','инструменты функции разделы все страницы'],
    ['features.html','Возможности','Что доступно на сайте Vainah VPN','функции'],
    ['about.html','О проекте','Как устроен Vainah VPN','команда'],
    ['glossary.html','Словарь VPN','Простые объяснения терминов','термины'],
    ['checklist.html','Чек-лист','Подготовка перед подключением','шаги']
  ];
  const searchTerms=(value)=>String(value||'').toLocaleLowerCase('ru').trim()
    .replace(/ё/g,'е')
    .replace(/телеграмм?/g,'telegram').replace(/роллипей/g,'rollypay')
    .replace(/айпад/g,'ipad').replace(/айфон/g,'iphone')
    .replace(/андроид/g,'android').replace(/виндовс/g,'windows')
    .replace(/макбук|макос/g,'macos')
    .replace(/[^\p{L}\p{N}]+/gu,' ').replace(/\s+/g,' ').trim();
  const el=(tag,cls,text)=>{
    const e=document.createElement(tag);
    if(cls)e.className=cls;
    if(text!==undefined)e.textContent=String(text);
    return e;
  };
  const path=window.location.pathname.split('/').pop()||'index.html';
  document.body.id=document.body.id||'vainah-top';
  const active=pages.find(p=>p[0]===path);
  const header=document.querySelector('body > header, body > .site-header');
  // The visual login label is shared across legacy pages. Keep screen readers
  // in sync with current email sign-in without changing auth callbacks.
  document.querySelectorAll('a.vainah-login').forEach(link=>{
    link.setAttribute('aria-label','Войти в личный кабинет Vainah VPN');
  });
  // A visible search entry on every page; it opens the same local command finder.
  const navTools=header?.querySelector('.nav-side,.header-actions');
  if(navTools&&!navTools.querySelector('.vx-header-search')){
    const search=el('button','vx-header-search','⌕');
    search.type='button';
    search.dataset.vxOpenSearch='';
    search.setAttribute('aria-label','Искать по сайту');
    search.title='Поиск по Vainah VPN (Ctrl+K)';
    const menu=navTools.querySelector('.hamburger,.menu-toggle');
    if(menu)navTools.insertBefore(search,menu);
    else navTools.append(search);
  }

  // Keep both generations of navigation usable at laptop and mobile widths.
  const extra=[
    ['command-hub.html','✦ Vainah Control'],
    ['hub.html','Центр управления'],
    ['trial.html','Пробный период · 0 ₽'],
    ['diagnostics.html','Диагностика'],
    ['library.html','Библиотека знаний'],
    ['speed.html','Проверка скорости'],
    ['network-check.html','Проверка соединения'],
    ['network-toolkit.html','Сетевые калькуляторы'],
    ['connection-monitor.html','Монитор сети'],
    ['browser-check.html','Проверка браузера'],
    ['repair-wizard.html','Мастер помощи'],
    ['tools.html','Все инструменты'],
    ['whats-new.html','Что нового']
  ];
  for(const nav of document.querySelectorAll('body > header .mobile-nav,body > header .drawer,body > .site-header .drawer')){
    for(const [href,label] of extra){
      if(nav.querySelector('a[href="'+href+'"]'))continue;
      const a=el('a','',label);a.href=href;nav.append(a);
    }
    if(!nav.querySelector('.vx-mobile-search')){
      const search=el('button','vx-mobile-search','⌕ Поиск по сайту');
      search.type='button';
      search.dataset.vxOpenSearch='';
      search.setAttribute('aria-label','Поиск по разделам сайта');
      nav.prepend(search);
    }
  }
  // Tell visitors when their browser has lost network connectivity.
  // Uses only browser online/offline events; no polling, accounts or API calls.
  if(header && !document.getElementById('vainah-offline-notice')){
    const notice=el('div','vx-offline-notice');
    notice.id='vainah-offline-notice';
    notice.setAttribute('role','status');
    notice.setAttribute('aria-live','polite');
    const updateNetworkNotice=()=>{
      const offline=navigator.onLine===false;
      notice.hidden=!offline;
      notice.textContent=offline
        ?'Нет подключения к сети (по данным браузера). Вход, платежи и диагностика могут быть недоступны.'
        :'';
    };
    header.after(notice);
    updateNetworkNotice();
    window.addEventListener('offline',updateNetworkNotice);
    window.addEventListener('online',updateNetworkNotice);
  }
  // A compact always-visible navigation rail exposes important pages even
  // when legacy desktop navigation is hidden at tablet/mobile widths.
  if(header && !document.querySelector('.vx-utility-rail')){
    const rail=el('nav','vx-utility-rail');
    rail.setAttribute('aria-label','Основные разделы Vainah VPN');
    const links=[
      ['index.html','⌂ Главная'],
      ['trial.html','✦ Бесплатно'],
      ['plans.html','▤ Тарифы'],
      ['account.html','▣ Мой VPN'],
      ['speed.html','↯ Тест скорости'],
      ['command-hub.html','✦ Vainah Control'],
      ['whats-new.html','✧ Новое'],
      ['contact.html','? Поддержка']
    ];
    for(const [href,label] of links){
      const a=el('a','vx-utility-link',label);
      a.href=href;
      if(path===href)a.setAttribute('aria-current','page');
      rail.append(a);
    }
    const searchButton=el('button','vx-utility-link vx-utility-search','⌕ Поиск');
    searchButton.type='button';
    searchButton.dataset.vxOpenSearch='';
    searchButton.setAttribute('aria-label','Поиск разделов Vainah VPN');
    rail.append(searchButton);
    header.after(rail);
  }
  // Make Vainah Control available alongside existing navigation.
  const desktopNav=header?.querySelector('.desktop-nav,.header-links');
  if(desktopNav && !desktopNav.querySelector('a[href="command-hub.html"]')){
    const center=el('a','vx-control-nav','✦ Центр Vainah');
    center.href='command-hub.html';
    desktopNav.prepend(center);
  }
  // Highlight the real trial flow on all public storefront pages.
  // The eligibility, issuance and H1Cloud quotas remain exclusively server-side.
  if(header && path !== 'trial.html'){
    const desktop=header.querySelector('.desktop-nav,.header-links');
    if(desktop && !desktop.querySelector('a[href="trial.html"]')){
      const a=el('a','vx-trial-nav','Пробный доступ · 0 ₽');
      a.href='trial.html';
      desktop.append(a);
    }
  }
  if(path === 'index.html' && !document.body.hasAttribute('data-refresh-home')){
    const mainForTrial=document.querySelector('main');
    if(mainForTrial && !mainForTrial.querySelector('.vx-trial-banner')){
      const banner=el('section','vx-trial-banner');
      banner.setAttribute('aria-label','Бесплатный пробный VPN');
      const copy=el('div','vx-trial-banner-copy');
      copy.append(
        el('strong','','Попробуй Vainah VPN бесплатно — 24 часа'),
        el('p','','10 ГБ на 2 устройства · без банковской карты · один раз после подтверждения email')
      );
      const cta=el('a','vx-trial-cta','Активировать за 0 ₽ →');
      cta.href='trial.html';
      banner.append(copy,cta);
      mainForTrial.prepend(banner);
    }
  }
  // Product entry points: visible even when an API endpoint is temporarily slow.
  // All links are ordinary first-party page navigations; no payment requests here.
  if(path === 'index.html' && !document.body.hasAttribute('data-refresh-home')){
    const home=document.querySelector('main');
    if(home&&!home.querySelector('.vx-journeys')){
      const journeys=el('section','vx-journeys');
      journeys.setAttribute('aria-label','Начни работу с Vainah VPN');
      const heading=el('div','vx-journeys-heading');
      const intro=el('div');
      intro.append(el('span','vx-journeys-eyebrow','БЫСТРЫЙ СТАРТ'),
        el('h2','','Всё нужное — за один шаг'),
        el('p','','Выбери, что хочешь сделать. Без лишних экранов и запутанных переходов.'));
      heading.append(intro);
      const cards=el('div','vx-journeys-grid');
      const options=[
        ['trial.html','01','Попробовать бесплатно','24 часа · 2 устройства · 10 ГБ','Бесплатный доступ','trial'],
        ['plans.html','02','Выбрать подписку','75 платных тарифов · от 2 до 730 дней','Смотреть тарифы','plans'],
        ['account.html','03','Открыть мой VPN','Подписка, ключ и история заказов','Личный кабинет','account'],
        ['device-center.html','04','Настроить устройство','Инструкция для телефона или компьютера','Подключение','devices']
      ];
      for(const [href,num,name,detail,action,kind] of options){
        const a=el('a','vx-journey vx-journey-'+kind);
        a.href=href;
        const number=el('span','vx-journey-number',num);
        const body=el('span','vx-journey-body');
        body.append(el('strong','',name),el('small','',detail),el('span','vx-journey-action',action+' →'));
        a.append(number,body);cards.append(a);
      }
      journeys.append(heading,cards);
      const notice=home.querySelector('.vx-trial-banner');
      if(notice)notice.after(journeys);
      else home.prepend(journeys);
    }
  }
  // Mark the selected page in navigations without changing destination URLs.
  for(const nav of document.querySelectorAll('body > header nav,body > .site-header nav')){
    for(const a of nav.querySelectorAll('a[href]')){
      const target=a.getAttribute('href')?.split('#')[0]?.split('?')[0];
      if(target===path)a.setAttribute('aria-current','page');
      else if(a.getAttribute('aria-current')==='page')a.removeAttribute('aria-current');
    }
  }

  if(header){
    const toggle=header.querySelector('[data-menu-button]');
    const mobile=header.querySelector('[data-mobile-nav]');
    if(toggle&&mobile){
      // Delegated listener also closes dynamically added navigation links.
      mobile.addEventListener('click',event=>{
        if(!event.target.closest('a'))return;
        mobile.classList.remove('open');
        toggle.setAttribute('aria-expanded','false');
        toggle.setAttribute('aria-label','Открыть меню');
      });
      document.addEventListener('keydown',event=>{
        if(event.key==='Escape'&&mobile.classList.contains('open')){
          mobile.classList.remove('open');
          toggle.setAttribute('aria-expanded','false');
          toggle.setAttribute('aria-label','Открыть меню');
          toggle.focus();
        }
      });
      document.addEventListener('click',event=>{
        if(!mobile.classList.contains('open'))return;
        if(!header.contains(event.target)){
          mobile.classList.remove('open');toggle.setAttribute('aria-expanded','false');
          toggle.setAttribute('aria-label','Открыть меню');
        }
      });
    }
  }

  const footer=document.querySelector('body > footer');
  const main=document.querySelector('main');
  if(main&&footer){
    const section=el('section','vx-explore');
    section.setAttribute('aria-label','Быстрые переходы по Vainah VPN');
    const inner=el('div','vx-explore-inner');
    const kicker=el('div','vx-explore-kicker','✦ VAINAH VPN · НАВИГАЦИЯ');
    const head=el('div','vx-explore-head');
    const info=el('div');
    info.append(el('h2','','Сервис всегда под рукой'),
      el('p','','Тарифы, твой VPN, диагностика и помощь — переходи без лишних шагов.'));
    const top=el('a','vx-up','↑ Наверх');top.href='#vainah-top';
    head.append(info,top);
    const grid=el('div','vx-explore-grid');
    const options=[
      ['hub.html','◉','Центр управления','Главная панель'],
      ['compare.html','≋','Сравнение тарифов','Все цены и сроки'],
      ['speed.html','↯','Тест скорости','Ping и скорость интернета'],
      ['network-toolkit.html','▤','Сетевые калькуляторы','12 инструментов расчёта скорости и трафика'],
      ['network-check.html','◉','Проверка сети','Доступность API и оплаты'],
      ['connection-monitor.html','≈','Монитор стабильности','Динамика задержки и ошибки'], 
      ['repair-wizard.html','?','Мастер помощи','Пошаговое решение проблем'],
      ['browser-check.html','◈','Браузер','Совместимость функций сайта'],
      ['diagnostics.html','↯','Диагностика','Проверки связи'],
      ['account.html','▦','Мой VPN','Личный кабинет']
    ];
    for(const [href,icon,name,subtitle] of options){
      const a=el('a','vx-explore-link');a.href=href;
      if(href===path){a.classList.add('vx-current-link');a.setAttribute('aria-current','page')}
      const ico=el('span','vx-explore-icon',icon);ico.setAttribute('aria-hidden','true');
      const t=el('span','vx-explore-text',name);t.append(el('small','',subtitle));
      a.append(ico,t);grid.append(a);
    }
    const quick=el('div','vx-explore-quick');
    const search=el('button','','⌕ Поиск по сайту · Ctrl+K');search.type='button';
    search.dataset.vxOpenSearch='';
    quick.append(search);
    for(const [href,name] of [['tools.html','Все инструменты'],['network-toolkit.html','Калькуляторы сети'],['network-check.html','Проверка сети'],['connection-monitor.html','Монитор стабильности'],['repair-wizard.html','Решить проблему'],['browser-check.html','Браузер'],['library.html','Библиотека знаний'],['device-center.html','Мастер подключения'],['contact.html','Поддержка']]){
      const a=el('a','',name);a.href=href;quick.append(a);
    }
    inner.append(kicker,head,grid,quick);section.append(inner);
    footer.before(section);
  }

  // Native modal is opened only by an explicit click or Ctrl/Cmd+K.
  const dialog=el('dialog','vx-finder');
  dialog.setAttribute('aria-label','Поиск разделов Vainah VPN');
  const form=el('form');form.method='dialog';
  const label=el('label','','БЫСТРЫЙ ПОИСК ПО САЙТУ');
  const input=el('input');input.type='search';input.autocomplete='off';
  input.setAttribute('aria-label','Найти раздел сайта');
  input.placeholder='Тарифы, iPad, помощь, оплата…';
  label.append(input);
  const close=el('button','vx-finder-close','Закрыть');close.type='submit';
  form.append(label,close);
  const list=el('div','vx-finder-list');list.id='vainah-finder-results';
  list.setAttribute('aria-live','polite');
  input.setAttribute('aria-controls',list.id);
  const tip=el('div','vx-finder-tip','Enter — открыть выбранный раздел · Esc — закрыть поиск');
  dialog.append(form,list,tip);document.body.append(dialog);
  const count=el('div','vx-finder-count');
  count.setAttribute('role','status');
  dialog.insertBefore(count,list);
  let selectedIndex=0;
  let currentResults=[];
  function activate(index){
    const results=[...list.querySelectorAll('a.vx-finder-result')];
    if(!results.length)return;
    selectedIndex=(index+results.length)%results.length;
    results.forEach((node,i)=>{
      if(i===selectedIndex)node.dataset.current='true';
      else delete node.dataset.current;
    });
    results[selectedIndex].scrollIntoView({block:'nearest'});
  }
  function render(){
    const q=searchTerms(input.value);
    const words=q.split(' ').filter(Boolean);
    currentResults=pages.map((page,i)=>{
      const [href,name,description,aliases]=page;
      const title=searchTerms(name);
      const combined=searchTerms(name+' '+description+' '+aliases);
      if(words.length && !words.every(word=>combined.includes(word)))return null;
      const score=q?(title===q?100:title.startsWith(q)?60:
        title.includes(q)?35:words.filter(w=>title.includes(w)).length*9+2):pages.length-i;
      return {page,score,index:i};
    }).filter(Boolean).sort((a,b)=>b.score-a.score||a.index-b.index).slice(0,18);
    count.textContent=currentResults.length
      ?'Найдено разделов: '+currentResults.length+(q?' · запрос: '+q:'')
      :'Нет совпадений — попробуй другое слово.';
    list.replaceChildren();
    if(!currentResults.length){
      list.append(el('div','vx-finder-empty','Ничего не найдено. Проверь запрос или открой все инструменты.'));
      return;
    }
    selectedIndex=0;
    for(const {page:[href,name,description]} of currentResults){
      const a=el('a','vx-finder-result');a.href=href;
      const glyph=el('span','vx-explore-icon','↗');glyph.setAttribute('aria-hidden','true');
      const body=el('span');
      body.append(el('b','',name),el('small','',description));
      a.append(glyph,body);list.append(a);
    }
    // Keyboard focus stays in the search field; Enter opens the highlighted link.
    const first=list.querySelector('a');
    if(first)first.dataset.current='true';
  }
  function openFinder(){
    input.value='';render();
    if(typeof dialog.showModal==='function'){
      if(!dialog.open)dialog.showModal();
    }else dialog.setAttribute('open','');
    input.focus();
  }
  function closeFinder(){
    if(typeof dialog.close==='function'&&dialog.open)dialog.close();
    else dialog.removeAttribute('open');
  }
  for(const button of document.querySelectorAll('[data-vx-open-search]'))
    button.addEventListener('click',openFinder);
  dialog.addEventListener('click',event=>{
    if(event.target===dialog)closeFinder();
  });
  input.addEventListener('input',render);
  input.addEventListener('keydown',event=>{
    if(event.key==='ArrowDown'||event.key==='ArrowUp'){
      if(!currentResults.length)return;
      event.preventDefault();
      activate(selectedIndex+(event.key==='ArrowDown'?1:-1));
    }else if(event.key==='Enter'){
      const found=list.querySelectorAll('a.vx-finder-result')[selectedIndex];
      if(found){event.preventDefault();window.location.assign(found.href)}
    }
  });
  document.addEventListener('keydown',event=>{
    const editable=event.target.closest?.('input,textarea,select,[contenteditable="true"]');
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){
      event.preventDefault();
      if(dialog.open)closeFinder();else openFinder();
    }else if(event.key==='/'&&!editable&&!event.altKey&&!event.metaKey&&!event.ctrlKey){
      event.preventDefault();
      if(!dialog.open)openFinder();
    }
  });

  // Lightweight, discoverable navigation for long pages, without any API calls.
  const privatePaths=new Set([
    'account.html','checkout.html','support-operator.html','operator-pilot.html',
    'operations.html','my-devices.html','notifications.html','gifts.html'
  ]);
  if(main&&path!=='index.html'&&!privatePaths.has(path)&&active){
    const trail=el('nav','vx-breadcrumbs');
    trail.setAttribute('aria-label','Путь по сайту');
    const home=el('a','','Главная');home.href='index.html';
    const divider=el('span','','/');
    divider.setAttribute('aria-hidden','true');
    trail.append(home,divider,el('span','vx-breadcrumb-current',active[1]));
    main.before(trail);
  }
  if(main&&document.body.scrollHeight>0){
    const back=el('button','vx-back-to-top','↑ Наверх');
    back.type='button';
    back.hidden=true;
    back.setAttribute('aria-label','Вернуться к началу страницы');
    document.body.append(back);
    let ticking=false;
    const updateBack=()=>{
      back.hidden=window.scrollY<640;
      ticking=false;
    };
    window.addEventListener('scroll',()=>{
      if(!ticking){ticking=true;requestAnimationFrame(updateBack)}
    },{passive:true});
    back.addEventListener('click',()=>{
      const reduce=window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
      window.scrollTo({top:0,behavior:reduce?'auto':'smooth'});
    });
    updateBack();
  }

  // Animate elements once they are on screen: never hide content awaiting JS.
  const prefersReduce=window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  if(!prefersReduce&&'IntersectionObserver' in window){
    const targets=document.querySelectorAll('main .ux-card,main .ux-plan,main .tool-card,main .ux-compare-item');
    const observer=new IntersectionObserver(entries=>{
      for(const entry of entries){
        if(entry.isIntersecting){
          entry.target.classList.add('vx-appear');
          observer.unobserve(entry.target);
        }
      }
    },{threshold:.06,rootMargin:'0px 0px 40px 0px'});
    for(const target of targets)observer.observe(target);
  }
  // Consistent purple design tokens and mobile focus styles on every shared
  // public page. Pure CSS: no checkout requests, auth or tracking.
  if(!document.querySelector('link[href*="vainah-next.css"]')){
    const design=document.createElement('link');
    design.rel='stylesheet';
    design.href='vainah-next.css?v=20261115-next2';
    design.dataset.vxNextTheme='1';
    document.head.append(design);
  }

  // Load the shared ULTRA UI layer without altering authentication or purchase JS.
  // Standalone benefits pages opt in with a static include instead.
  if (!document.querySelector('link[data-vx-ultra]')) {
    const style=document.createElement('link');
    style.rel='stylesheet';
    style.href='ultra-experience.css?v=20261113-ultra4';
    style.dataset.vxUltra='style';
    document.head.append(style);
  }
  if (!document.querySelector('script[data-vx-ultra]')) {
    const script=document.createElement('script');
    script.src='ultra-experience.js?v=20261113-ultra4';
    script.dataset.vxUltra='script';
    script.defer=true;
    document.head.append(script);
  }
  // Ultra Control: a standalone accessible task hub; only public navigation.
  // Keeping it isolated prevents UI changes from affecting auth or payments.
  if (!document.querySelector('link[data-vx-control]')) {
    const style = document.createElement('link');
    style.rel = 'stylesheet';
    style.href = 'ultra-control.css?v=20261114-chat1';
    style.dataset.vxControl = 'style';
    document.head.append(style);
  }
  if (!document.querySelector('script[data-vx-control]')) {
    const script = document.createElement('script');
    script.src = 'ultra-control.js?v=20261114-chat1';
    script.defer = true;
    script.dataset.vxControl = 'script';
    document.head.append(script);
  }
  // Ultra 360: fast, accessible mobile navigation only on informational pages.
  // Never covers a live checkout, account screen or one-time auth controls.
  const noMobileRail=new Set([
    'checkout.html','checkout-return.html','payment-return.html',
    'account.html','account-login.html','operator-pilot.html',
    'operations.html','support-operator.html','support-center.html',
    'my-devices.html','gifts.html','gift-cards.html','trial.html'
  ]);
  if(!noMobileRail.has(path)&&!document.querySelector('[data-vx-ultra-rail]')){
    const rail=el('nav','vx-ultra-mobile-rail');
    rail.dataset.vxUltraRail='true';
    rail.setAttribute('aria-label','Быстрая навигация на телефоне');
    const links=[
      ['⌂','Главная','index.html'],
      ['◈','Тарифы','plans.html'],
      ['✦','Помощь','ultra-repair.html'],
      ['▣','Кабинет','account.html']
    ];
    for(const [symbol,name,url] of links){
      const a=el('a','vx-ultra-mobile-link');
      a.href=url;
      if(path===url)a.setAttribute('aria-current','page');
      a.append(el('span','vx-ultra-mobile-icon',symbol),el('span','',name));
      rail.append(a);
    }
    document.body.append(rail);
    document.body.classList.add('vx-has-ultra-mobile');
  }
  // CSS is loaded after the existing chat styles to keep launcher and
  // floating accessibility controls above the small-screen navigation.
  if(!document.querySelector('link[data-vx-ultra-mobile]')){
    const style=document.createElement('link');
    style.rel='stylesheet';
    style.href='ultra-mobile.css?v=20261115-u360';
    style.dataset.vxUltraMobile='1';
    document.head.append(style);
  }
  // Don't trigger continuous decorative motion on metered/data-saver devices.
  // The old floating quick-actions prototype duplicated Ultra Control.
  // Vainah Control is now a full page accessible from navigation.
  // At desktop zoom levels above the tablet breakpoint, fall back to
  // the accessible dropdown if the expanded navigation would overlap actions.
  // No polling or user tracking: only resize and font-loading events.
  if(header?.matches('body > header') &&
     header.querySelector('.desktop-nav,.nav-side,.hamburger')){
    const checkHeaderFit=()=>{
      if(window.innerWidth<=1680){
        header.classList.remove('vx-header-collapsed');
        return;
      }
      header.classList.remove('vx-header-collapsed');
      const nav=header.querySelector('.desktop-nav');
      const actions=header.querySelector('.nav-side');
      const logo=header.querySelector('.nav-wrap > .logo');
      if(!nav||!actions||!logo)return;
      const navRect=nav.getBoundingClientRect();
      const actionsRect=actions.getBoundingClientRect();
      const logoRect=logo.getBoundingClientRect();
      header.classList.toggle('vx-header-collapsed',
        navRect.right>actionsRect.left-12 ||
        navRect.left<logoRect.right+6 ||
        actionsRect.right>window.innerWidth-8
      );
    };
    window.addEventListener('resize',checkHeaderFit,{passive:true});
    if(document.fonts?.ready)void document.fonts.ready.then(checkHeaderFit);
    checkHeaderFit();
  }
  // No timers or background API polling are created by the shared shell.
  // Add one shared, isolated finishing layer rather than more inline page CSS.
  if(!document.querySelector('link[data-vx-quality]')){
    const style=document.createElement('link');
    style.rel='stylesheet';
    style.href='site-upgrade.css?v=20261118-quality1';
    style.dataset.vxQuality='css';
    document.head.append(style);
  }
  if(!document.querySelector('script[data-vx-quality]')){
    const script=document.createElement('script');
    script.src='site-health.js?v=20261118-ipad2';
    script.defer=true;
    script.dataset.vxQuality='js';
    document.head.append(script);
  }
  // Tablet-first layout loads last, after legacy page design systems.
  if(!document.querySelector('link[data-vx-adaptive]')){
    const style=document.createElement('link');
    style.rel='stylesheet';
    style.href='responsive-fit.css?v=20261118-ipad2';
    style.dataset.vxAdaptive='css';
    document.head.append(style);
  }
  // The task-first homepage and public tariff workspace share one final
  // stylesheet. It never alters checkout/auth/network behavior.
  if(!document.querySelector('link[data-vx-experience-v5]')){
    const sheet=document.createElement('link');
    sheet.rel='stylesheet';
    sheet.href='experience-v5.css?v=20261118-mega1';
    sheet.dataset.vxExperienceV5='style';
    document.head.append(sheet);
  }
  // Ultra 6: private-by-design navigation preferences on informational pages.
  // No network access, payments, authentication, or private page history.
  if(!document.querySelector('link[data-vx-ultra6]')){
    const sheet=document.createElement('link');
    sheet.rel='stylesheet';
    sheet.href='ultra6-workspace.css?v=20261118-u6a';
    sheet.dataset.vxUltra6='css';
    document.head.append(sheet);
  }
  if(!document.querySelector('script[data-vx-ultra6]')){
    const script=document.createElement('script');
    script.src='ultra6-workspace.js?v=20261118-u6a';
    script.defer=true;
    script.dataset.vxUltra6='js';
    document.head.append(script);
  }
})();
