/* Vainah Ultra 6.0: privacy-first personal workspace.
 * Stores only whitelisted public page filenames and visual preferences locally.
 * No network, no account data, no cookies, no VPN keys, no checkout actions.
 */
(() => {
  'use strict';
  const key = 'vainah-ultra6-workspace-v1';
  const allowed = Object.freeze({
    'index.html': ['Главная', '⌂'],
    'command-hub.html': ['Vainah Control', '✦'],
    'plans.html': ['Тарифы и сравнение', '▤'],
    'devices.html': ['Устройства', '⌘'],
    'device-center.html': ['Мастер подключения', '◈'],
    'connect.html': ['Подключение', '↗'],
    'servers.html': ['Локации', '◎'],
    'guide.html': ['Инструкция', '▣'],
    'features.html': ['Возможности', '✧'],
    'about.html': ['О проекте', '◉'],
    'help.html': ['Вопросы и ответы', '?'],
    'library.html': ['Библиотека знаний', '▦'],
    'tools.html': ['Инструменты', '∑'],
    'ultra-repair.html': ['Решение проблем', '✧'],
    'troubleshooting.html': ['Диагностика', '↯'],
    'privacy.html': ['Конфиденциальность', '◇'],
    'terms.html': ['Условия сервиса', '▤'],
    'whats-new.html': ['Что нового', '✦'],
    'compare.html': ['Сравнить подписки', '≋'],
    'assistant.html': ['Подобрать подписку', '✧'],
    'start.html': ['Быстрый старт', '↗'],
    'glossary.html': ['Словарь VPN', 'A'],
    'checklist.html': ['Чек-лист', '✓'],
    'network-toolkit.html': ['Сетевые калькуляторы', '∑'],
    'browser-check.html': ['Проверка браузера', '◈'],
    'repair-wizard.html': ['Мастер помощи', '?'],
    'security.html': ['Безопасность', '◇']
  });
  const contains = value => Object.prototype.hasOwnProperty.call(allowed,value);
  const normalizedList = (value,max) => Array.isArray(value)
    ? [...new Set(value.filter(item=>typeof item==='string'&&contains(item)))].slice(0,max)
    : [];
  let memoryOnly=false;
  const read = () => {
    try {
      const raw=window.localStorage.getItem(key);
      if(!raw)return null;
      const value=JSON.parse(raw);
      return value&&typeof value==='object'&&!Array.isArray(value)?value:null;
    }catch {memoryOnly=true;return null;}
  };
  const original=read()||{};
  const settings={
    contrast:original.settings?.contrast===true,
    readable:original.settings?.readable===true,
    motion:original.settings?.motion===true
  };
  const state={
    pins: normalizedList(original.pins,6),
    recent:normalizedList(original.recent,5),
    settings,
    historyEnabled:original.historyEnabled!==false
  };
  const save=()=>{
    try{window.localStorage.setItem(key,JSON.stringify(state));memoryOnly=false;}
    catch{memoryOnly=true;}
  };
  const page=(location.pathname.split('/').pop()||'index.html').toLowerCase();
  // Do not record account, payment, support tickets or operator pages.
  if(contains(page)&&state.historyEnabled){
    state.recent=[page,...state.recent.filter(p=>p!==page)].slice(0,5);
    save();
  }
  const root=document.documentElement;
  const reflectSettings=()=>{
    root.classList.toggle('vx6-contrast',state.settings.contrast);
    root.classList.toggle('vx6-readable',state.settings.readable);
    root.classList.toggle('vx6-no-motion',state.settings.motion);
  };
  reflectSettings();
  const node=(tag,cls,text)=>{
    const n=document.createElement(tag);
    if(cls)n.className=cls;
    if(text!==undefined)n.textContent=text;
    return n;
  };
  const createLink=(id,additionalClass='')=>{
    const a=node('a','vx6-link '+additionalClass);
    a.href=id; // Fixed, whitelisted first-party filenames only.
    a.append(node('span','vx6-link-icon',allowed[id][1]));
    const label=node('span','vx6-link-text');
    label.append(node('strong','',allowed[id][0]));
    if(id===page)label.append(node('small','','Сейчас открыто'));
    a.append(label);
    if(id===page)a.setAttribute('aria-current','page');
    return a;
  };
  const status=document.querySelector('[data-vx6-status]');
  const announce=message=>{if(status)status.textContent=message;};
  const pinned=document.querySelector('[data-vx6-pinned]');
  const recent=document.querySelector('[data-vx6-recent]');
  const button=document.querySelector('[data-vx6-history-toggle]');
  const refresh=()=>{
    if(pinned){
      pinned.replaceChildren();
      if(!state.pins.length)pinned.append(node('p','vx6-empty',
        'Здесь появятся избранные разделы. Нажми «☆ Сохранить» на любой информационной странице.'));
      for(const id of state.pins){
        const item=node('div','vx6-pin-item');
        const link=createLink(id);
        const remove=node('button','vx6-unpin','×');
        remove.type='button';
        remove.setAttribute('aria-label','Убрать '+allowed[id][0]+' из быстрых ссылок');
        remove.addEventListener('click',()=>{
          state.pins=state.pins.filter(p=>p!==id);save();refresh();
          announce('Раздел удалён из быстрых ссылок.');
        });
        item.append(link,remove);pinned.append(item);
      }
    }
    if(recent){
      recent.replaceChildren();
      if(!state.historyEnabled){
        recent.append(node('p','vx6-empty','История посещённых разделов отключена.'));
      }else if(!state.recent.length){
        recent.append(node('p','vx6-empty','История пока пуста.'));
      }else for(const id of state.recent)recent.append(createLink(id,'vx6-recent-link'));
    }
    if(button){
      button.setAttribute('aria-pressed',String(state.historyEnabled));
      button.textContent=state.historyEnabled?'Приостановить историю':'Включить историю';
    }
    document.querySelectorAll('[data-vx6-preference]').forEach(b=>{
      const name=b.dataset.vx6Preference;
      if(!Object.prototype.hasOwnProperty.call(settings,name))return;
      b.setAttribute('aria-pressed',String(state.settings[name]));
    });
    for(const pin of document.querySelectorAll('[data-vx6-pin-current]')){
      const isPinned=state.pins.includes(page);
      pin.textContent=isPinned?'★ В быстрых ссылках':'☆ Сохранить раздел';
      pin.setAttribute('aria-pressed',String(isPinned));
    }
    if(memoryOnly)announce('Частный режим браузера: изменения сохраняются только до закрытия страницы.');
  };
  const togglePin=()=>{
    if(!contains(page))return;
    if(state.pins.includes(page)){
      state.pins=state.pins.filter(p=>p!==page);
      announce('Раздел убран из быстрых ссылок.');
    }else if(state.pins.length<6){
      state.pins.push(page);
      announce('Раздел сохранён. Найди его в Vainah Control.');
    }else{
      announce('Можно сохранить не больше 6 разделов. Удали один в Vainah Control.');
      return;
    }
    save();refresh();
  };
  const privateSections=new Set([
    'checkout.html','account.html','trial.html','payment-return.html',
    'checkout-return.html','account-login.html','support-center.html',
    'support-operator.html','gifts.html','gift-cards.html','notifications.html',
    'my-devices.html','operator-pilot.html','operations.html'
  ]);
  // Do not add personalization controls to any sensitive or unknown page.
  if(contains(page)&&!privateSections.has(page)&&page!=='command-hub.html'){
    const parent=document.querySelector('.vx-breadcrumbs');
    if(parent){
      const pin=node('button','vx6-pin-current');
      pin.type='button';
      pin.dataset.vx6PinCurrent='';
      pin.addEventListener('click',togglePin);
      parent.append(pin);
    }
  }
  document.querySelector('[data-vx6-pin-home]')?.addEventListener('click',togglePin);
  document.querySelector('[data-vx6-clear-history]')?.addEventListener('click',()=>{
    state.recent=[];
    save();refresh();announce('История посещённых разделов очищена.');
  });
  button?.addEventListener('click',()=>{
    state.historyEnabled=!state.historyEnabled;
    if(!state.historyEnabled)state.recent=[];
    save();refresh();
    announce(state.historyEnabled?'История включена.':'История отключена и очищена.');
  });
  document.querySelectorAll('[data-vx6-preference]').forEach(b=>{
    b.addEventListener('click',()=>{
      const name=b.dataset.vx6Preference;
      if(!Object.prototype.hasOwnProperty.call(settings,name))return;
      state.settings[name]=!state.settings[name];
      reflectSettings();save();refresh();
      announce('Настройка отображения изменена.');
    });
  });
  refresh();
  // A small home card uses the same local safe data without repeating the hub.
  const home=document.querySelector('[data-vx6-home-continue]');
  if(home){
    const last=state.recent.find(id=>id!=='index.html');
    const link=home.querySelector('[data-vx6-home-link]');
    if(last&&link){
      link.href=last;
      link.textContent='Продолжить: '+allowed[last][0]+' ↗';
    }else if(link){
      link.href='command-hub.html';
      link.textContent='Открыть мои быстрые ссылки ↗';
    }
    const copy=home.querySelector('[data-vx6-home-copy]');
    if(copy)copy.textContent=state.historyEnabled
      ?'Недавние разделы и закреплённые страницы доступны только в этом браузере.'
      :'История отключена. Ты всегда можешь включить её в Vainah Control.';
  }
})();