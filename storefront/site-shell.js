/* Vainah VPN shared site shell: no account data, no external calls, no payment actions. */
(function(){
  'use strict';
  const pages=[
    ['index.html','Главная','Начало, новости сайта, навигация','главная'],
    ['hub.html','Центр управления','Личный кабинет, подписки и состояние сервисов','аккаунт управление сервисы'],
    ['plans.html','Тарифы','Цены всех 6 подписок','цены купить 30 60 90 180 365'],
    ['compare.html','Сравнение тарифов','Сравнить сроки, стоимость и устройства','разница тарифов цена'],
    ['assistant.html','Подобрать тариф','Помощник по сроку и количеству устройств','выбрать подобрать'],
    ['account.html','Личный кабинет','VPN, срок, заказы и история после Telegram Login','мой впн мой vpn продление телеграм'],
    ['checkout.html','Оформление на сайте','Выбор подписки. Реальные платежи пока выключены','оплата роллипей касса'],
    ['device-center.html','Мастер подключения','Пошаговая настройка и чек-лист','установка устройство конфигурация'],
    ['devices.html','Все устройства','iPhone, iPad, Android, Windows, macOS','телефон айфон планшет'],
    ['guide.html','Инструкция','Импорт VPN-конфигурации','настройка ключ'],
    ['start.html','Быстрый старт','С чего начать, если подписки нет','новичок'],
    ['status.html','Статус сервисов','H1Cloud, PostgreSQL, RollyPay и webhook','недоступность сбой'],
    ['diagnostics.html','Центр диагностики','Проверки соединения и решения проблем','не работает ошибка'],
    ['troubleshooting.html','Решение проблем','Диагностика импорта, ошибок и соединения','помощь ошибка'],
    ['help.html','Ответы на вопросы','FAQ про подписку и подключение','частые вопросы'],
    ['library.html','Библиотека знаний','Поиск по материалам проекта','справочник статьи'],
    ['contact.html','Поддержка','Обращение в службу поддержки','связь написать'],
    ['servers.html','Серверы','Локации и доступность панели','локации страны'],
    ['security.html','Безопасность','Защита личной конфигурации','приватность'],
    ['privacy.html','Конфиденциальность','Как сайт обращается с данными','данные'],
    ['terms.html','Условия сервиса','Правила использования Vainah VPN','условия'],
    ['speed.html','Скорость','Что влияет на производительность VPN','задержка медленно'],
    ['features.html','Возможности','Что доступно на сайте Vainah VPN','функции'],
    ['about.html','О проекте','Как устроен Vainah VPN','команда'],
    ['glossary.html','Словарь VPN','Простые объяснения терминов','термины'],
    ['checklist.html','Чек-лист','Подготовка перед подключением','шаги']
  ];
  const searchTerms=(value)=>String(value||'').toLocaleLowerCase('ru').trim()
    .replace(/ё/g,'е')
    .replace(/телеграмм?/g,'telegram').replace(/роллипей/g,'rollypay')
    .replace(/айпад/g,'ipad').replace(/айфон/g,'iphone')
    .replace(/андроид/g,'android').replace(/виндовс/g,'windows');
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

  // Keep both generations of navigation usable at laptop and mobile widths.
  const extra=[
    ['hub.html','Центр управления'],
    ['diagnostics.html','Диагностика'],
    ['library.html','Библиотека знаний']
  ];
  for(const nav of document.querySelectorAll('body > header .mobile-nav,body > header .drawer,body > .site-header .drawer')){
    for(const [href,label] of extra){
      if(nav.querySelector('a[href="'+href+'"]'))continue;
      const a=el('a','',label);a.href=href;nav.append(a);
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
    for(const [href,name] of [['library.html','Библиотека знаний'],['device-center.html','Мастер подключения'],['contact.html','Поддержка']]){
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
  function render(){
    const q=searchTerms(input.value);
    const matched=pages.filter(([href,name,description,aliases])=>{
      if(!q)return true;
      return searchTerms(name+' '+description+' '+aliases).includes(q);
    }).slice(0,15);
    list.replaceChildren();
    if(!matched.length){
      list.append(el('div','vx-finder-empty','Ничего не найдено. Попробуй другое слово.'));
      return;
    }
    for(const [href,name,description] of matched){
      const a=el('a','vx-finder-result');a.href=href;
      const glyph=el('span','vx-explore-icon','↗');glyph.setAttribute('aria-hidden','true');
      const body=el('span');
      body.append(el('b','',name),el('small','',description));
      a.append(glyph,body);list.append(a);
    }
  }
  function openFinder(){
    input.value='';render();
    if(typeof dialog.showModal==='function'){if(!dialog.open)dialog.showModal()}
    else dialog.setAttribute('open','');
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
    if(event.key==='Enter'){
      const first=list.querySelector('a');
      if(first){event.preventDefault();window.location.assign(first.href)}
    }
  });
  document.addEventListener('keydown',event=>{
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){
      event.preventDefault();
      if(dialog.open)closeFinder();else openFinder();
    }
  });

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
  // No timers or background API polling are created by the shared shell.
})();
