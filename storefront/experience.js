/* Enhanced site tools: tariff comparison and read-only diagnostics. */
(function(){
  'use strict';
  function $(s,root=document){return root.querySelector(s)}
  function $$(s,root=document){return [...root.querySelectorAll(s)]}
  const formatter=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2});
  const compare=$('[data-compare]');
  if(compare){
    const device=$('[data-devices-filter]',compare);
    const duration=$('[data-duration-filter]',compare);
    const order=$('[data-sort-filter]',compare);
    const count=$('[data-compare-count]',compare);
    const empty=$('[data-compare-empty]',compare);
    const grid=$('[data-compare-grid]',compare);
    const table=$('.ux-table tbody',compare);
    const loading=$('[data-compare-loading]',compare);
    let cards=$$('[data-plan-days][data-plan-kopeks][data-plan-devices]',grid);
    const futureIds=new Set([]);
    const validIds=new Set(['trial-free','7','14','30','45','60','90','120','180','365','30-family','365-family','mini-3d','sprint-5d','start-plus-21d','balance-75d','comfort-150d','max-270d','legend-730d','family-plus-90d','family-pro-180d','family-max-730d',
    'pulse-2d','flash-4d','weekend-9d','jump-10d','express-12d','boost-17d','start-25d','flex-35d','focus-40d','smart-50d','steady-55d','stream-65d','prime-100d','flow-135d','power-210d','advance-240d','ultra-300d','horizon-540d','family-week-7d','family-14d','family-21d','family-45d','family-60d','family-75d','family-120d','family-150d','family-240d','family-270d','family-540d','personal-6d','personal-8d','personal-11d','personal-13d','personal-16d','personal-19d','personal-23d','personal-28d','personal-42d','personal-70d','personal-105d','personal-165d','personal-225d','personal-330d','personal-450d','family-3d','family-5d','family-10d','family-28d','family-35d','family-100d','family-135d','family-210d','family-300d','family-450d']);
    const paidIds=new Set(['7','14','30','45','60','90','120','180','365','30-family','365-family','mini-3d','sprint-5d','start-plus-21d','balance-75d','comfort-150d','max-270d','legend-730d','family-plus-90d','family-pro-180d','family-max-730d',
    'pulse-2d','flash-4d','weekend-9d','jump-10d','express-12d','boost-17d','start-25d','flex-35d','focus-40d','smart-50d','steady-55d','stream-65d','prime-100d','flow-135d','power-210d','advance-240d','ultra-300d','horizon-540d','family-week-7d','family-14d','family-21d','family-45d','family-60d','family-75d','family-120d','family-150d','family-240d','family-270d','family-540d','personal-6d','personal-8d','personal-11d','personal-13d','personal-16d','personal-19d','personal-23d','personal-28d','personal-42d','personal-70d','personal-105d','personal-165d','personal-225d','personal-330d','personal-450d','family-3d','family-5d','family-10d','family-28d','family-35d','family-100d','family-135d','family-210d','family-300d','family-450d']);
    const fmt=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2});
    function isSafe(p){
      return p&&validIds.has(p.id)&&
        typeof p.title==='string'&&p.title.length>0&&p.title.length<=60&&
        Number.isInteger(p.days)&&p.days>=1&&p.days<=730&&
        Number.isInteger(p.devices)&&p.devices>=2&&p.devices<=6&&
        typeof p.price_rub==='string'&&/^(0|[1-9][0-9]{0,5})\.[0-9]{2}$/.test(p.price_rub)&&
        ['trial','existing','upcoming'].includes(p.status)&&
        (p.status==='trial'?(p.id==='trial-free'&&p.price_rub==='0.00'&&p.traffic_gb===10):
        p.status==='existing'?paidIds.has(p.id)&&p.checkout_supported===true&&
          p.checkout_path==='/checkout.html?plan='+p.id:
        p.status==='upcoming'&&futureIds.has(p.id)&&p.checkout_supported===false&&
          p.checkout_path===null);
    }
    function elem(tag,contents,cls){
      const result=document.createElement(tag);
      if(contents!==undefined)result.textContent=String(contents);
      if(cls)result.className=cls;
      return result;
    }
    function action(p){
      if(p.status==='trial'){
        const link=elem('a','Пробный день ↗','btn btn-primary');
        link.href='/trial.html';return link;
      }
      if(p.status==='existing'&&paidIds.has(p.id)&&p.checkout_supported===true&&
        p.checkout_path==='/checkout.html?plan='+p.id){
        const link=elem('a','Выбрать тариф ↗','btn btn-primary');
        link.href=p.checkout_path;return link;
      }
      const button=elem('button','Скоро · в подготовке','btn btn-border');
      button.type='button';button.disabled=true;return button;
    }
    function makeCard(p){
      const card=elem('article',undefined,'ux-compare-item');
      card.dataset.planDays=String(p.days);
      card.dataset.planDevices=String(p.devices);
      card.dataset.planKopeks=String(Math.round(Number(p.price_rub)*100));
      card.append(elem('span',
        p.status==='trial'?'БЕСПЛАТНО':
        p.status==='upcoming'?'СКОРО':
        p.devices===6?'СЕМЕЙНЫЙ':'ДЕЙСТВУЕТ','ux-plan-badge'));
      card.append(elem('h2',p.title));
      card.append(elem('div',fmt.format(Number(p.price_rub))+' ₽','ux-plan-price'));
      card.append(elem('p',p.status==='upcoming'?
        'Предложение предварительное, пока не продаётся.':
        p.status==='trial'?'10 ГБ, без платежа':
        'Действующий тариф, доступность оплаты проверяется при заказе.','ux-plan-info'));
      const details=elem('div',undefined,'ux-compare-detail');
      for(const [label,value] of [
        ['Срок',p.days+' дней'],
        ['Устройства','До '+p.devices],
        ['Трафик',p.status==='trial'?'10 ГБ':p.status==='upcoming'?
          'Условия уточняются':'Безлимитный'],
        ['Цена за 30 дней*',p.status==='trial'?'0 ₽':
          '≈ '+fmt.format(Math.round(Number(p.price_rub)*30/p.days))+' ₽']
      ]){
        const row=elem('div');
        row.append(elem('span',label),elem('strong',value));
        details.append(row);
      }
      card.append(details,action(p));return card;
    }
    function makeTableRow(p){
      const row=elem('tr');
      for(const value of [
        p.title,p.days+' дней',String(p.devices),
        p.status==='trial'?'10 ГБ':p.status==='upcoming'?
          'Условия уточняются':'Безлимитный',
        fmt.format(Number(p.price_rub))+' ₽'
      ])row.append(elem('td',value));
      const last=elem('td');
      const link=action(p);
      if(link.tagName==='A')link.textContent='Открыть ↗';
      last.append(link);row.append(last);return row;
    }
    function update(){
      const d=device.value,t=duration.value,sort=order.value;
      const visible=cards.filter(card=>{
        const days=Number(card.dataset.planDays),devices=Number(card.dataset.planDevices);
        const matchDevices=d==='all'||String(devices)===d;
        const matchDuration=t==='all'||(t==='short'?days<=90:
          t==='medium'?days>=91&&days<180:days>=180);
        card.hidden=!(matchDevices&&matchDuration);
        return !card.hidden;
      });
      visible.sort((a,b)=>{
        const aCost=Number(a.dataset.planKopeks),bCost=Number(b.dataset.planKopeks);
        const aDays=Number(a.dataset.planDays),bDays=Number(b.dataset.planDays);
        return sort==='total'?aCost-bCost:
          sort==='value'?aCost/aDays-bCost/bDays:aDays-bDays;
      });
      for(const card of visible)grid.append(card);
      count.textContent=visible.length+' из '+cards.length+' вариантов';
      empty.hidden=visible.length>0;
    }
    for(const control of [device,duration,order])control.addEventListener('change',update);
    update();
    fetch('/api/site/tariffs',{cache:'no-store',credentials:'omit',
      headers:{Accept:'application/json'}}).then(async response=>{
      if(!response.ok)throw Error('HTTP '+response.status);
      const data=await response.json();
      if(data.total!==76||!Array.isArray(data.plans)||data.plans.length!==76||
        !data.plans.every(isSafe)||
        new Set(data.plans.map(p=>p.id)).size!==76||
        data.plans.filter(p=>p.status==='existing').length!==75||
        data.plans.filter(p=>p.status==='upcoming').length!==0||
        data.plans.filter(p=>p.status==='trial').length!==1
      )throw Error('CATALOG_MISMATCH');
      const newCards=data.plans.map(makeCard);
      grid.replaceChildren(...newCards);
      if(table)table.replaceChildren(...data.plans.map(makeTableRow));
      cards=newCards;
      update();
      if(loading)loading.textContent=
        'Все 76 предложений: 75 платных тарифов и 1 бесплатный пробный день. Оплата проверяется при заказе.';
    }).catch(()=>{
      // Keep the 6 original verified cards AND table if API is down.
      if(loading)loading.textContent=
        'Новые предложения не загрузились. Показаны только действующие тарифы.';
    });
  }

  const pageStatus=$('[data-service-status]');
  if(pageStatus){
    const checks=['database','h1','rollypay','webhook'];
    const button=$('[data-status-refresh]',pageStatus);
    const updated=$('[data-status-updated]',pageStatus);
    async function refreshConfig(){
      // Each public GET reports only configuration; never claim a real login
      // or send a code, invoke OAuth or create a support ticket here.
      const providers=[
        {id:'email',url:'/api/email-auth/config',badge:'Email настроен',
          ready:'Вход по одноразовому коду настроен. Отправка и доставка писем здесь не проверяются.',
          missing:'Вход по email пока не настроен. Обратись в поддержку.'},
        {id:'google',url:'/api/google/config',badge:'OAuth настроен',
          ready:'Google OAuth настроен на сервере. Успешный вход подтверждается только при авторизации.',
          missing:'Google OAuth пока не настроен. Можно воспользоваться входом по email.'},
        {id:'telegram',url:'/api/telegram-oidc/config',badge:'OIDC настроен',
          ready:'Telegram OIDC настроен. Проверка авторизации через Telegram здесь не выполняется.',
          missing:'Telegram OIDC пока недоступен. Используй другой способ входа.'},
        {id:'telegram-classic',url:'/api/telegram/config',badge:'Widget настроен',
          ready:'Telegram Login Widget настроен. Для реального входа также требуется разрешённый домен бота.',
          missing:'Классический Telegram Widget не настроен. Доступны другие способы входа.'},
        {id:'support',url:'/api/support/config',badge:'Поддержка настроена',
          ready:'Поддержка доступна для вошедших пользователей.',
          missing:'Сервис обращений пока не настроен. Используй страницу контактов.'},
      ];
      await Promise.all(providers.map(async item=>{
        const element=$('[data-config-card="'+item.id+'"]',pageStatus);
        if(!element)return;
        const badge=$('[data-status-label]',element);
        const detail=$('[data-status-detail]',element);
        try{
          const response=await fetch(item.url,{
            method:'GET',cache:'no-store',credentials:'omit',
            headers:{Accept:'application/json'}
          });
          if(!response.ok)throw Error('HTTP '+response.status);
          const config=await response.json();
          if(!config || typeof config.available!=='boolean')throw Error('Invalid response');
          if(config.available){
            badge.textContent=item.badge;
            badge.dataset.kind='configured';
            detail.textContent=item.ready + (
              item.id==='support' ?
                (config.email_notifications_available===true
                  ? ' Email-уведомления оператора настроены.'
                  : ' Email-уведомления оператора не подтверждены.')
                : ''
            );
          }else{
            badge.textContent='Не настроено';
            badge.dataset.kind='unknown';
            detail.textContent=item.missing;
          }
        }catch{
          badge.textContent='Нет данных';
          badge.dataset.kind='unknown';
          detail.textContent='Ответ конфигурации временно недоступен. Это не доказывает сбой сервиса.';
        }
      }));
    }
    async function refresh(){
      button.disabled=true;
      button.textContent='Проверяем сервисы…';
      updated.textContent='Проверяем доступность API H1Cloud/RollyPay в режиме чтения. Подписка не создаётся.';
      try{
        const response=await fetch('/api/site/services',{
          method:'GET',cache:'no-store',headers:{Accept:'application/json'}
        });
        if(!response.ok)throw Error('API '+response.status);
        const data=await response.json();
        if(!data||!data.services)throw Error('Некорректный формат');
        let okCount=0;
        for(const id of checks){
          const element=$('[data-status-card="'+id+'"]',pageStatus);
          if(!element)continue;
          const badge=$('[data-status-label]',element);
          const detail=$('[data-status-detail]',element);
          const item=data.services[id];
          if(item&&item.status==='verified'){
            badge.dataset.kind='ok';badge.textContent='Подтверждено';okCount++;
          }else if(item&&item.status==='received'){
            badge.dataset.kind='unknown';badge.textContent='Webhook получен';
          }else if(item&&item.status==='ok'){
            badge.dataset.kind='ok';badge.textContent='Проверка пройдена';okCount++;
          }else if(item&&item.status==='sandbox'){
            badge.dataset.kind='unknown';badge.textContent='Тестовый режим';
          }else if(item&&item.status==='configured'){
            badge.dataset.kind='unknown';badge.textContent='Настроено';
          }else if(item&&item.status==='error'){
            badge.dataset.kind='unknown';badge.textContent='Ошибка доступа';
          }else if(item&&item.status==='unavailable'){
            badge.dataset.kind='unknown';badge.textContent='Связь не подтверждена';
          }else{
            badge.dataset.kind='unknown';badge.textContent='Не подключено';
          }
          detail.textContent=item&&item.message?item.message:'Нет подтверждённых данных.';
        }
        updated.textContent='Проверено: '+new Date().toLocaleTimeString('ru-RU',{
          hour:'2-digit',minute:'2-digit'
        })+'. Подтверждённых работающих сервисов: '+okCount+' из '+checks.length+
        '. Настройка входа и история платежей не заменяют проверку реальной авторизации.';
      }catch(err){
        for(const id of checks){
          const element=$('[data-status-card="'+id+'"]',pageStatus);
          if(!element)continue;
          const badge=$('[data-status-label]',element);
          const detail=$('[data-status-detail]',element);
          badge.dataset.kind='unknown';badge.textContent='Нет данных';
          detail.textContent='Python API не ответил. Проверь запуск локального сайта.';
        }
        updated.textContent='Не удалось получить данные с Python-сервера: '+err.message;
      }finally{
        button.disabled=false;button.textContent='↻ Обновить статусы';
        void refreshConfig();
      }
    }
    button.addEventListener('click',refresh);
    refresh();
  }

  const launch=$('[data-checkout-message]');
  if(launch){
    fetch('/api/shop/config',{cache:'no-store',credentials:'omit'})
      .then(r=>r.ok?r.json():Promise.reject(Error('plans')))
      .then(data=>{
        launch.textContent=data.checkout_ready===true?
          'Онлайн-оформление доступно после подтверждения email. Оплата через RollyPay.':
          'Сейчас новые платежи временно недоступны. Попробуй позже или обратись в поддержку.';
      })
      .catch(()=>{
        launch.textContent='Проверить доступность онлайн-оплаты можно на странице тарифов.';
      });
  }
})();
