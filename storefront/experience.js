/* Enhanced site tools: tariff comparison and read-only diagnostics. */
(function(){
  'use strict';
  function $(s,root=document){return root.querySelector(s)}
  function $$(s,root=document){return [...root.querySelectorAll(s)]}
  const formatter=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2});
  // Static Render pages must request read-only data from the Python origin.
  // Cross-origin reads may be denied by CORS; treat that as unknown, not offline.
  const publicApi=typeof location!=='undefined' && location.origin==='https://vainahvpn.onrender.com'
    ? 'https://vainahvpn-python-preview.onrender.com' : '';

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
    const retry=$('[data-compare-retry]',compare);
    const tableView=$('[data-compare-table]',compare);
    const pluralDays=new Intl.PluralRules('ru');
    const term=days=>days+' '+{one:'день',few:'дня',many:'дней'}[pluralDays.select(days)];
    let rows=null;

    function isSafe(plan){
      if(!plan||typeof plan.id!=='string'||!/^[a-z0-9-]{1,60}$/.test(plan.id)||
         typeof plan.title!=='string'||!plan.title.trim()||plan.title.length>60||
         !Number.isInteger(plan.days)||plan.days<1||plan.days>730||
         typeof plan.price_rub!=='string'||!/^(0|[1-9][0-9]{0,5})\.[0-9]{2}$/.test(plan.price_rub))return false;
      if(plan.id==='trial-free')return plan.status==='trial'&&plan.days===1&&
        plan.devices===2&&plan.price_rub==='0.00'&&plan.traffic_gb===10&&
        plan.checkout_supported===false&&plan.checkout_path==='/trial.html';
      return plan.status==='existing'&&[3,6].includes(plan.devices)&&Number(plan.price_rub)>0&&
        plan.checkout_supported===true&&plan.checkout_path==='/checkout.html?plan='+plan.id;
    }
    function elem(tag,value,cls){
      const node=document.createElement(tag);
      if(value!==undefined)node.textContent=String(value);
      if(cls)node.className=cls;
      return node;
    }
    function action(plan){
      const trial=plan.status==='trial';
      const link=elem('a',trial?'Пробный день ↗':'Выбрать тариф ↗','btn btn-primary');
      link.href=(trial?'':publicApi)+plan.checkout_path;
      return link;
    }
    const price=plan=>formatter.format(Number(plan.price_rub))+' ₽';
    const daily=plan=>formatter.format(Number(plan.price_rub)/plan.days)+' ₽';
    function makeCard(plan){
      const card=elem('article',undefined,'ux-compare-item');
      card.append(
        elem('h3',plan.title),
        elem('div',price(plan),'ux-plan-price'),
        elem('p',term(plan.days)+' · До '+plan.devices+' устройств','ux-plan-info'),
        elem('p',plan.status==='trial'?'10 ГБ':daily(plan)+' за день','ux-plan-info'),
        action(plan)
      );
      return card;
    }
    function makeTableRow(plan){
      const row=elem('tr');
      const name=elem('th',plan.title);
      name.scope='row';
      row.append(name);
      for(const value of [term(plan.days),plan.devices,price(plan),daily(plan)]){
        row.append(elem('td',value));
      }
      const last=elem('td');
      last.append(action(plan));
      row.append(last);
      return row;
    }
    function update(){
      if(!rows)return;
      const devices=device.value,period=duration.value,sort=order.value;
      const visible=rows.filter(({plan})=>{
        const days=plan.days;
        return (devices==='all'||String(plan.devices)===devices)&&
          (period==='all'||(period==='short'?days<=90:period==='medium'?days<180&&days>90:days>=180));
      });
      visible.sort(({plan:a},{plan:b})=>{
        const aCost=Number(a.price_rub),bCost=Number(b.price_rub);
        if(sort==='total')return aCost-bCost||a.days-b.days;
        if(sort==='value')return aCost/a.days-bCost/b.days||aCost-bCost;
        return a.days-b.days||aCost-bCost;
      });
      grid.replaceChildren(...visible.map(row=>row.card));
      table?.replaceChildren(...visible.map(row=>row.cells));
      count.textContent=visible.length+' из '+rows.length+' вариантов';
      empty.hidden=visible.length>0;
      if(tableView)tableView.hidden=!visible.length;
    }
    async function loadComparison(){
      if(retry)retry.hidden=true;
      if(loading)loading.textContent='Загружаем тарифы…';
      const controller=new AbortController();
      const timeout=setTimeout(()=>controller.abort(),15000);
      try{
        const response=await fetch(publicApi+'/api/site/tariffs',{
          cache:'no-store',credentials:'omit',signal:controller.signal,
          headers:{Accept:'application/json'}
        });
        if(!response.ok)throw Error('HTTP '+response.status);
        const data=await response.json();
        const plans=data?.plans;
        if(!Array.isArray(plans)||plans.length<2||data.total!==plans.length||
           !plans.every(isSafe)||new Set(plans.map(plan=>plan.id)).size!==plans.length||
           plans.filter(plan=>plan.status==='trial').length!==1)throw Error('CATALOG_MISMATCH');
        rows=plans.map(plan=>({plan,card:makeCard(plan),cells:makeTableRow(plan)}));
        update();
        if(loading)loading.textContent=plans.length+' предложений · цены с сервера';
      }catch{
        count.textContent='';
        if(loading)loading.textContent='Не удалось загрузить актуальные тарифы.';
        if(retry)retry.hidden=false;
      }finally{clearTimeout(timeout);}
    }
    for(const control of [device,duration,order])control.addEventListener('change',update);
    retry?.addEventListener('click',loadComparison);
    void loadComparison();
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
        {id:'email',badge:'Email настроен',
          ready:'Вход по одноразовому коду настроен. Отправка и доставка писем здесь не проверяются.',
          missing:'Вход по email пока не настроен. Обратись в поддержку.'},
        {id:'google',badge:'OAuth настроен',
          ready:'Google OAuth настроен на сервере. Успешный вход подтверждается только при авторизации.',
          missing:'Google OAuth пока не настроен. Можно воспользоваться входом по email.'},
        {id:'telegram',badge:'OIDC настроен',
          ready:'Telegram OIDC настроен. Проверка авторизации через Telegram здесь не выполняется.',
          missing:'Telegram OIDC пока недоступен. Используй другой способ входа.'},
        {id:'telegram-classic',badge:'Widget настроен',
          ready:'Telegram Login Widget настроен. Для реального входа также требуется разрешённый домен бота.',
          missing:'Классический Telegram Widget не настроен. Доступны другие способы входа.'},
        {id:'support',badge:'Поддержка настроена',
          ready:'Поддержка доступна для вошедших пользователей.',
          missing:'Сервис обращений пока не настроен. Используй страницу контактов.'},
      ];
      let readiness=null;
      try{
        const response=await fetch(publicApi+'/api/site/readiness',{
          method:'GET',cache:'no-store',credentials:'omit',
          headers:{Accept:'application/json'}
        });
        if(response.ok)readiness=await response.json();
      }catch{}
      for(const item of providers){
        const element=$('[data-config-card="'+item.id+'"]',pageStatus);
        if(!element)continue;
        const badge=$('[data-status-label]',element);
        const detail=$('[data-status-detail]',element);
        const configured=readiness?.[item.id];
        if(configured===true){
          badge.textContent=item.badge;
          badge.dataset.kind='configured';
          detail.textContent=item.ready+(item.id==='support'&&readiness.support_email===true
            ? ' Email-уведомления настроены.' : '');
        }else{
          badge.textContent=configured===false?'Не настроено':'Нет данных';
          badge.dataset.kind='unknown';
          detail.textContent=configured===false?item.missing:'Не удалось проверить конфигурацию.';
        }
      }
    }
    async function refresh(){
      button.disabled=true;
      button.textContent='Проверяем сервисы…';
      updated.textContent='Проверяем доступность API H1Cloud/RollyPay в режиме чтения. Подписка не создаётся.';
      try{
        const response=await fetch(publicApi+'/api/site/services',{
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
          detail.textContent='Ответ публичного API не подтверждён. Возможны ограничения CORS или задержка Render; это не доказывает сбой backend.';
        }
        updated.textContent='Публичные статусы временно не удалось прочитать. Данные о работе сервисов не подтверждены.';
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
    fetch(publicApi+'/api/shop/config',{cache:'no-store',credentials:'omit'})
      .then(r=>r.ok?r.json():Promise.reject(Error('plans')))
      .then(data=>{
        if(typeof data?.checkout_ready!=='boolean'||typeof data?.platega_ready!=='boolean')
          throw Error('INVALID_CHECKOUT_STATUS');
        const gateways=[data.checkout_ready?'RollyPay':null,data.platega_ready?'Platega':null].filter(Boolean);
        launch.textContent=gateways.length?
          'Доступные кассы: '+gateways.join(' и ')+'. Для оплаты подтверди email.':
          'Сейчас новые платежи временно недоступны. Попробуй позже или обратись в поддержку.';
      })
      .catch(()=>{
        launch.textContent='Не удалось проверить доступность кассы из браузера; уточни статус на странице оформления.';
      });
  }
})();
