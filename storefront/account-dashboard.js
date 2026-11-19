/* Verified Telegram and email dashboard. Never fabricate subscriptions. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const write=(id,value)=>{const node=$(id);if(node)node.textContent=value;};
  const hide=(id,value)=>{const node=$(id);if(node)node.hidden=value;};
  let user=null;
  let subscriptionUrl=null;
  let manualGrantUrl=null;
  let privateQrUrl=null;
  let qrPending=false;
  let currentData=null;
  let historyOrders=[];
  let sessionEpoch=0;
  let refreshEpoch=0;
  // A connection guide may suggest a client, but cannot trigger an import
  // without the subscriber's own click on the installed application.
  const params=new URLSearchParams(window.location?.search||'');
  const requestedClient=params.get('client');
  const selectedClient=['happ','incy'].includes(requestedClient)?requestedClient:null;
  const checkoutLink=$('account-checkout-link');
  const checkoutPanel=$('account-checkout-panel');
  const checkoutPlanKey='vainah-checkout-plan';
  try{
    if(sessionStorage.getItem('vainah-checkout-return')==='1'){
      hide('account-payment-return',false);
      sessionStorage.removeItem('vainah-checkout-return');
    }
  }catch{}
  if(checkoutLink&&checkoutPanel){
    let checkoutParams=params;
    try{
      if(!params.has('plan')){
        checkoutParams=new URLSearchParams(sessionStorage.getItem(checkoutPlanKey)||'');
      }
    }catch{}
    const plan=checkoutParams.get('plan');
    const gateway=checkoutParams.get('gateway');
    if(plan&&/^[a-z0-9-]{1,60}$/.test(plan)){
      const selection=new URLSearchParams({plan});
      if(gateway==='platega'||gateway==='rollypay')selection.set('gateway',gateway);
      try{sessionStorage.setItem(checkoutPlanKey,selection.toString());}catch{}
      checkoutLink.href='checkout.html?'+selection+'#shop-payment-panel';
      checkoutPanel.hidden=false;
      checkoutLink.addEventListener('click',()=>{
        try{sessionStorage.removeItem(checkoutPlanKey);}catch{}
      });
    }
  }
  const clientName=client=>client==='incy'?'INCY':'Happ';
  function setAccountHealth(message,state='checking'){
    write('account-dashboard-health',message);
    $('account-dashboard-health')?.setAttribute?.('data-state',state);
  }
  function showImportIntent(available=false){
    const hint=$('account-import-intent');
    if(!hint)return;
    if(!selectedClient){hint.hidden=true;return;}
    hint.hidden=false;
    hint.textContent=available
      ?'Ты выбрал '+clientName(selectedClient)+'. Нажми выделенную кнопку «Подключиться через '+
        clientName(selectedClient)+'». Браузер может спросить разрешение открыть приложение.'
      :'Ты выбрал '+clientName(selectedClient)+'. Проверяем наличие подписки перед импортом.';
    for(const [id,client] of [
      ['account-open-happ','happ'],['account-open-incy','incy'],
      ['account-manual-happ','happ'],['account-manual-incy','incy']
    ]){
      const link=$(id);
      link?.classList?.toggle('account-client-preferred',available&&client===selectedClient);
    }
  }
  async function api(path,options={}){
    const response=await fetch(path,{
      credentials:'same-origin',
      cache:'no-store',
      headers:{Accept:'application/json',...(options.headers||{})},
      ...options
    });
    const body=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(
      typeof body.detail==='string'?body.detail:'Ошибка сервера ('+response.status+')'
    );
    return body;
  }
  function clientImportLink(client,rawUrl){
    // Happ and INCY use different actions for an HTTPS subscription.
    // The URL is deliberately preserved as a nested URL (not base64 or
    // encodeURIComponent), as documented by both clients.
    const url=new URL(rawUrl);
    if(url.protocol!=='https:'||url.username||url.password||url.hash)
      throw Error('INVALID_SUBSCRIPTION_URL');
    const prefix=client==='happ'?'happ://add/':
      client==='incy'?'incy://import/':null;
    if(!prefix)throw Error('UNSUPPORTED_CLIENT');
    return prefix+url.href;
  }
  function updateClientLinks(url,manual=false){
    const list=manual
      ?[['account-manual-happ','happ'],['account-manual-incy','incy']]
      :[['account-open-happ','happ'],['account-open-incy','incy']];
    for(const [id,client] of list){
      const link=$(id);
      if(!link)continue;
      link.href=clientImportLink(client,url);
      link.referrerPolicy='no-referrer';
      link.hidden=false;
    }
    showImportIntent(true);
  }
  function registerImportFallback(id,client,manual=false){
    const link=$(id);
    if(!link)return;
    link.addEventListener('click',()=>{
      const url=manual?manualGrantUrl:subscriptionUrl;
      if(!user||!url||link.hidden||link.getAttribute?.('href')===null)return;
      const session=sessionEpoch,revision=refreshEpoch;
      const target=manual?'account-manual-status':'account-access-status';
      // A direct link click (not async navigation) retains the user gesture
      // needed by mobile browsers to launch an installed VPN client.
      // Copy in the same gesture as a fallback if the handler is unavailable.
      write(target,'Пробуем открыть '+clientName(client)+
        ' для импорта подписки. Подтверди переход в приложение, если браузер спросит.');
      if(navigator.clipboard?.writeText){
        void navigator.clipboard.writeText(url).then(()=>{
          if(session!==sessionEpoch||revision!==refreshEpoch)return;
          write(target,'Переход в '+clientName(client)+
            ' запрошен, а личная ссылка скопирована в буфер обмена. '+
            'Если импорт не появился — добавь её через «+» в клиенте.');
        }).catch(()=>{
          if(session!==sessionEpoch||revision!==refreshEpoch)return;
          write(target,'Открываем приложение. Если импорт не появился, вернись сюда и нажми «Скопировать ссылку».');
        });
      }
      // Do not preventDefault, await, or call location after fetching:
      // those patterns lose the external-protocol user gesture.
    });
  }
  const safeString=value=>typeof value==='string'?value:'';
  function formatDate(value){
    if(!value)return 'Не указана';
    const date=new Date(value);
    if(Number.isNaN(date.getTime()))return 'Не указана';
    return new Intl.DateTimeFormat('ru-RU',{day:'2-digit',month:'short',year:'numeric'}).format(date);
  }
  const statusNames={
    delivered:'Оплачено · выдано',paid:'Оплачено · выдаётся',
    issued:'Выдано без оплаты',verification_pending:'Проверка H1Cloud',
    pending:'Ожидает оплаты',created:'Ожидает оплаты',
    reserved:'Счёт создаётся',claimed:'Оплачено · доступ готовится',
    manual_review:'Требуется проверка',
    processing:'Обрабатывается',cancelled:'Отменён',canceled:'Отменён',
    expired:'Истёк',failed:'Ошибка обработки',
    needs_review:'Требуется проверка',
    refund:'Возврат',refunded:'Возврат'
  };
  function orderStatus(value){
    return statusNames[safeString(value)]||'Статус уточняется';
  }
  function displayOrderStatus(order){
    return order.paid===true&&order.status==='pending'?'paid':order.status;
  }
  function statusClass(value){
    return value==='delivered'?'success':
      value==='pending'||value==='created'||value==='paid'||value==='processing'?'pending':'';
  }
  function historyView(){
    const query=safeString($('account-order-search')?.value).trim().toLocaleLowerCase('ru').replace(/ё/g,'е');
    const filter=safeString($('account-order-filter')?.value)||'all';
    const sort=safeString($('account-order-sort')?.value)||'newest';
    const matched=historyOrders.filter(order=>{
      const title=safeString(order.title).toLocaleLowerCase('ru').replace(/ё/g,'е');
      if(query&&!title.includes(query))return false;
      const status=safeString(displayOrderStatus(order));
      if(filter==='delivered'&&status!=='delivered')return false;
      if(filter==='waiting'&&!['reserved','created','pending','paid','claimed','processing','needs_review','manual_review'].includes(status))return false;
      if(filter==='closed'&&!['cancelled','canceled','expired','failed','revoked','refunded','refund','chargeback'].includes(status))return false;
      return true;
    });
    return matched.sort((a,b)=>{
      const dateA=new Date(a.created_at).getTime();
      const dateB=new Date(b.created_at).getTime();
      const valueA=Number.isFinite(dateA)?dateA:0;
      const valueB=Number.isFinite(dateB)?dateB:0;
      return sort==='oldest'?valueA-valueB:valueB-valueA;
    });
  }
  function showHistory(){
    const items=historyView();
    write('account-history-match',historyOrders.length
      ?'Показано: '+items.length+' из '+historyOrders.length:'Нет подтверждённых покупок');
    const exportButton=$('account-order-export');
    if(exportButton)exportButton.disabled=!user||!items.length;
    renderOrders(items);
  }
  function csvCell(value){
    const raw=String(value??'');
    // Spreadsheet viewers may execute cells beginning with formula markers.
    const safe=/^[\s]*[=+@-]/.test(raw)?"'"+raw:raw;
    return '"'+safe.replace(/"/g,'""')+'"';
  }
  function exportHistory(){
    if(!user||!currentData)return;
    const rows=historyView();
    if(!rows.length)return;
    const csv=[
      ['Тариф','Дата','Статус'].map(csvCell).join(','),
      ...rows.map(order=>[
        safeString(order.title)||'VPN-подписка',
        formatDate(order.created_at),
        orderStatus(displayOrderStatus(order))
      ].map(csvCell).join(','))
    ].join('\r\n');
    try{
      const blob=new Blob(['\uFEFF',csv],{type:'text/csv;charset=utf-8'});
      const link=document.createElement('a');
      const url=URL.createObjectURL(blob);
      link.href=url;link.download='vainah-vpn-orders.csv';
      link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
      write('account-history-hint','Экспортированы только отображаемые заказы. VPN-ключи и email не включены.');
    }catch{
      write('account-history-hint','Не удалось сохранить CSV в этом браузере.');
    }
  }
  function renderOrders(orders){
    const history=$('account-order-list');
    if(!history)return;
    history.replaceChildren();
    if(!orders.length){
      const empty=document.createElement('div');
      empty.className='account-empty';
      const heading=document.createElement('strong');
      heading.textContent=historyOrders.length?'По запросу ничего не найдено':'Пока нет заказов';
      const detail=document.createElement('span');
      detail.textContent=historyOrders.length
        ?'Измени фильтр или очисти строку поиска.'
        :'Начни с пробного периода или выбери тариф.';
      const actions=document.createElement('div');
      actions.className='account-empty-actions';
      for(const [href,label] of (historyOrders.length?[]:[['trial.html','Пробный доступ'],['plans.html','Выбрать тариф']])){
        const link=document.createElement('a');
        link.href=href;link.className='btn btn-border';link.textContent=label;actions.append(link);
      }
      empty.append(heading,detail,actions);history.append(empty);
      return;
    }
    for(const order of orders){
      const row=document.createElement('article');
      row.className='account-order';
      const title=document.createElement('div');
      title.className='order-name';
      title.textContent=safeString(order.title)||'VPN-подписка';
      const date=document.createElement('div');
      date.className='order-sub';
      date.textContent=formatDate(order.created_at);
      const amount=document.createElement('div');
      amount.className='order-amount';
      amount.textContent=/^[0-9]+\.[0-9]{2}$/.test(order.amount_rub)
        ?new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(Number(order.amount_rub))+' ₽'
        :'—';
      const state=document.createElement('div');
      const status=displayOrderStatus(order);
      state.className='order-state '+statusClass(status);
      state.textContent=orderStatus(status);
      row.append(title,date,amount,state);
      history.append(row);
    }
  }
  function formatBytes(value){
    if(!Number.isSafeInteger(value)||value<0)return '—';
    if(value===0)return '0 Б';
    const units=['Б','КиБ','МиБ','ГиБ','ТиБ','ПиБ'];
    let amount=value,index=0;
    while(amount>=1024&&index<units.length-1){amount/=1024;index++;}
    return new Intl.NumberFormat('ru-RU',{maximumFractionDigits:index?2:0}).format(amount)+' '+units[index];
  }
  function updateTraffic(subscription){
    const traffic=subscription?.traffic;
    const used=traffic?.used_bytes;
    const limit=traffic?.limit_bytes;
    const knownUsed=Number.isSafeInteger(used)&&used>=0;
    const knownLimit=Number.isSafeInteger(limit)&&limit>0;
    const available=knownUsed||knownLimit;
    write('account-traffic-used',knownUsed?formatBytes(used):'Нет данных');
    write('account-traffic-limit',knownLimit?formatBytes(limit):'Нет данных');
    write('account-traffic-left',knownUsed&&knownLimit?
      formatBytes(Math.max(0,limit-used)):'Нет данных');
    write('account-traffic-badge',available?'Данные H1Cloud':'Нет статистики');
    write('account-traffic-note',available
      ?(knownUsed&&knownLimit
        ?'Данные получены из H1Cloud. Остаток рассчитан по подтверждённым байтам.'
        :'H1Cloud передал только часть показателей. Недостающие значения не рассчитываются.')
      :'H1Cloud не предоставил проверенную статистику трафика для этой подписки.');
    const progress=$('account-traffic-progress');
    const fill=$('account-traffic-fill');
    if(progress){
      const canCalculate=knownUsed&&knownLimit;
      progress.hidden=!canCalculate;
      const percent=canCalculate?Math.min(100,Math.round(used/limit*100)):0;
      progress.setAttribute?.('aria-valuenow',String(percent));
      if(fill?.style)fill.style.width=percent+'%';
    }
  }

  function buildAdvisories(data){
    const notices=[];
    const sub=data?.subscription;
    const confirmed=(sub?.paid===true&&sub?.status==='delivered')||
      (sub?.paid===false&&sub?.gifted===true&&sub?.status==='issued');
    const h1status=safeString(data?.h1cloud?.status);
    const orders=Array.isArray(data?.orders)?data.orders:[];
    const hasPaid=orders.some(order=>order&&order.paid===true&&
      (order.delivered===true||order.status==='delivered'));
    if(!data)return notices;
    if(!confirmed){
      if(hasPaid&&['unavailable','inactive','not_found','not_configured'].includes(h1status)){
        notices.push({
          kind:'warning',title:'Подписка оплачена, но состояние H1Cloud не подтверждено',
          detail:'Покупка есть в истории, однако провайдер не смог подтвердить активный VPN-профиль. Не покупай повторно из-за этой проверки.',
          href:'support-center.html',action:'Обратиться в поддержку'
        });
      }else{
        notices.push({
          kind:'info',title:'Пока нет подтверждённой активной подписки',
          detail:'После подтверждённой оплаты или ручной выдачи H1Cloud здесь появятся данные о сроке и трафике.',
          href:'plans.html',action:'Посмотреть тарифы'
        });
      }
      return notices;
    }
    const rawExpiry=typeof sub.expires_at==='string'?sub.expires_at:'';
    const expiry=rawExpiry?new Date(rawExpiry).getTime():NaN;
    if(!Number.isFinite(expiry)){
      notices.push({
        kind:'info',title:'Дата окончания сейчас неизвестна',
        detail:'H1Cloud не передал проверенную дату. Не делай выводов об окончании подписки по этой карточке.',
        href:'support-center.html',action:'Уточнить срок'
      });
    }else{
      const remaining=expiry-Date.now();
      if(remaining<=0){
        notices.push({
          kind:'warning',title:'Указанная H1Cloud дата окончания уже прошла',
          detail:'Обнови кабинет и проверь реальный статус подключения. Это не подтверждение, что VPN отключён.',
          href:'support-center.html',action:'Проверить с поддержкой'
        });
      }else if(remaining<=3*86400000){
        notices.push({
          kind:'warning',title:'До окончания подписки осталось менее трёх дней',
          detail:'Это предупреждение рассчитано по дате H1Cloud. При необходимости продли подписку.',
          href:'plans.html',action:'Посмотреть продление'
        });
      }else if(remaining<=7*86400000){
        notices.push({
          kind:'info',title:'Подписка заканчивается в ближайшие семь дней',
          detail:'Проверь дату в личном кабинете и при желании сохрани календарное напоминание.',
          href:'#account-calendar',action:'Напоминание в календарь'
        });
      }
    }
    const used=sub.traffic?.used_bytes,limit=sub.traffic?.limit_bytes;
    if(Number.isSafeInteger(used)&&used>=0&&
        Number.isSafeInteger(limit)&&limit>0){
      const ratio=used/limit;
      if(ratio>=1){
        notices.push({
          kind:'warning',title:'По счётчикам H1Cloud трафик достиг указанного лимита',
          detail:'Счётчики могут обновляться с задержкой. Проверь остаток в кабинете и условия подписки.',
          href:'support-center.html',action:'Помощь с трафиком'
        });
      }else if(ratio>=0.9){
        notices.push({
          kind:'warning',title:'Использовано больше 90% лимита трафика',
          detail:'Расчёт основан на проверенных байтах H1Cloud, а не на оценке браузера.',
          href:'plans.html',action:'Посмотреть тарифы'
        });
      }else if(ratio>=0.75){
        notices.push({
          kind:'info',title:'Использовано больше 75% лимита трафика',
          detail:'Следи за статистикой в разделе «Использование VPN».',
          href:'#account-traffic',action:'Проверить трафик'
        });
      }
    }
    if(!notices.length){
      notices.push({
        kind:'ok',title:'Срочных предупреждений в полученных данных нет',
        detail:'Это относится только к проверенной дате и доступным счётчикам H1Cloud, а не к работе всего VPN-туннеля.',
        href:'status.html',action:'Состояние сервисов'
      });
    }
    return notices;
  }
  function renderAdvisories(data){
    const target=$('account-alert-list');
    const notices=buildAdvisories(data);
    if(!target)return;
    target.replaceChildren();
    write('account-alerts-badge',data
      ?notices.some(item=>item.kind==='warning')?'Нужно внимание':'Обновлено из H1Cloud'
      :'Данные скрыты');
    if(!data){
      const message=document.createElement('p');
      message.textContent='Проверка состояния появится после входа и обновления подписки.';
      target.append(message);return;
    }
    for(const notice of notices){
      const card=document.createElement('div');
      card.className='account-alert account-alert-'+notice.kind;
      const title=document.createElement('strong');
      title.textContent=notice.title;
      const detail=document.createElement('p');
      detail.textContent=notice.detail;
      const link=document.createElement('a');
      link.href=notice.href;
      link.textContent=notice.action+' →';
      card.append(title,detail,link);
      target.append(card);
    }
  }

  function validExpiry(value){
    if(typeof value!=='string'||!value.trim())return null;
    const date=new Date(value);
    return Number.isFinite(date.getTime())&&date.getTime()>Date.now()?date:null;
  }
  function updatePrivateActions(){
    const ready=!!user&&currentData?.subscription?.status==='delivered'&&
      currentData?.subscription?.paid===true;
    const calendar=$('account-calendar');
    if(calendar)calendar.disabled=!ready||!validExpiry(currentData?.subscription?.expires_at);
    const summary=$('account-support-summary');
    if(summary)summary.disabled=!user||!currentData;
  }
  function updateExpiryNote(value){
    const date=typeof value==='string'?new Date(value):null;
    if(!date||!Number.isFinite(date.getTime())){
      write('account-expiry-note','Срок неизвестен: проверенные данные H1Cloud отсутствуют.');
      return;
    }
    const days=Math.ceil((date.getTime()-Date.now())/86400000);
    write('account-expiry-note',days<=0
      ?'Указанная дата уже прошла. Обнови кабинет, чтобы проверить состояние подписки.'
      :days<=7
      ?'Подписка заканчивается в ближайшие '+days+' дн. Проверь варианты продления.'
      :'По данным H1Cloud до указанной даты около '+days+' дн.');
  }
  function clearQR(){
    if(privateQrUrl){
      URL.revokeObjectURL(privateQrUrl);
      privateQrUrl=null;
    }
    const qrImage=$('account-qr-image');
    if(qrImage){qrImage.removeAttribute('src');qrImage.hidden=true;}
    const qrButton=$('account-get-qr');
    if(qrButton)qrButton.textContent='Показать QR для подключения';
    hide('account-qr-panel',true);
    write('account-qr-status','QR ещё не запрошен.');
  }
  function clearSubscription(){
    clearQR();
    subscriptionUrl=null;
    manualGrantUrl=null;
    showImportIntent(false);
    hide('account-manual-copy',true);
    for(const id of ['account-manual-happ','account-manual-incy']){
      const element=$(id);
      if(element){element.removeAttribute('href');element.hidden=true;}
    }
    write('account-manual-status','Подарочная подписка ещё не проверена.');
    const open=$('account-open-vpn');
    if(open)open.removeAttribute('href');
    hide('account-open-vpn',true);
    for(const id of ['account-open-happ','account-open-incy']){
      const link=$(id);
      if(link){link.removeAttribute('href');link.hidden=true;}
    }
    hide('account-copy-vpn',true);
    const copy=$('account-copy-vpn');
    if(copy)copy.disabled=true;
    const get=$('account-get-vpn');
    if(get)get.disabled=true;
    const qrButton=$('account-get-qr');
    if(qrButton)qrButton.disabled=true;
    updateTraffic(null);
    updateExpiryNote(null);
    renderAdvisories(null);
    updatePrivateActions();
    write('metric-plan','Нет подтверждённых покупок');
    write('metric-expiry','—');
    write('metric-devices','—');
    write('account-plan-name','Подписка не оформлена');
    write('account-plan-sub','Выберите тариф для оформления подписки.');
    write('account-plan-price','—');
    write('account-plan-chip','Нет оплаченного заказа');
    write('account-access-status','Ключ будет доступен после подтверждения оплаты и выдачи персональной подписки.');
    write('account-device-limit','—');
    write('account-device-note','Лимит появится после покупки.');
  }
  function resetPrivate(){
    currentData=null;
    historyOrders=[];
    const search=$('account-order-search');if(search)search.value='';
    const filter=$('account-order-filter');if(filter)filter.value='all';
    const sort=$('account-order-sort');if(sort)sort.value='newest';
    write('account-history-match','Нет подтверждённых покупок');
    const exportButton=$('account-order-export');if(exportButton)exportButton.disabled=true;
    hide('account-support-manual',true);
    write('account-calendar-status','Напоминание появится, когда H1Cloud подтвердит дату окончания подписки. Календарь не создаётся автоматически.');
    clearSubscription();
    hide('account-test-vpn',true);
    const testList=$('account-test-vpn-list');
    if(testList)testList.replaceChildren();
    write('account-h1-state','Проверяем H1Cloud…');
    write('account-email-status','Проверяем подтверждённую почту…');
    for(const id of ['account-email-input','account-email-code']){
      const input=$(id);if(input)input.value='';
    }
    write('account-history-count','0');
    setAccountHealth(user?'Проверяем актуальные данные подписки…':'Войди в аккаунт, чтобы проверить подписку.');
    write('account-history-hint','В истории отображаются только подтверждённые покупки.');
    const history=$('account-order-list');
    if(history)history.textContent='Пока нет подтверждённых покупок.';
  }
  function showSession(next){
    sessionEpoch++;
    user=next||null;resetPrivate();
    if(typeof window.dispatchEvent==='function'){
      window.dispatchEvent(new Event('vainah-account-session'));
    }
    hide('account-auth-panel',!!user);
    hide('account-private',!user);
    hide('account-alt-private',true);
    hide('account-exit',!user);
    const emailUser=user?.auth_method==='email';
    write('account-user',user
      ? (emailUser?user.email:(user.username?'@'+user.username:'Telegram ID '+user.telegram_id))
      :'Гость');
    write('account-avatar',user
      ? (emailUser?user.email.slice(0,1):(user.first_name||'T').slice(0,1)).toUpperCase()
      :'V');
    hide('account-email-form',!!emailUser);
    hide('account-email-verify',true);
    hide('account-checkout-link',!emailUser);
    hide('account-checkout-verify',!!emailUser);
    if(user)void refresh();
  }
  function errorMessage(error){
    switch(error?.message){
      case 'TELEGRAM_LOGIN_NOT_CONFIGURED':return 'Telegram не настроен в Render.';
      case 'TELEGRAM_AUTH_INVALID':return 'Telegram не подтвердил вход. Повтори попытку.';
      case 'INVALID_ORIGIN':return 'Адрес сайта не совпал. Проверь домен Render.';
      default:return 'Ошибка входа: '+(error?.message||'Неизвестная ошибка');
    }
  }
  window.onVainahAccountAuth=async(data)=>{
    write('account-auth-status','Проверяем подпись Telegram на сервере…');
    try{
      const result=await api('/api/telegram/account',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({action:'login',data})
      });
      if(!result.authenticated||!result.user)throw Error('LOGIN_FAILED');
      showSession(result.user);
    }catch(error){write('account-auth-status',errorMessage(error));}
  };
  window.onVainahEmailAuth=next=>showSession(next);

  async function refresh(){
    if(!user)return;
    const session=sessionEpoch;
    const revision=++refreshEpoch;
    currentData=null;
    historyOrders=[];
    setAccountHealth('Обновляем данные подписки и проверяем H1Cloud…');
    showHistory();
    clearSubscription();
    hide('account-test-vpn',true);
    const testList=$('account-test-vpn-list');
    if(testList)testList.replaceChildren();
    void refreshTestSubscriptions(session,revision);
    const refreshButton=$('account-refresh');
    if(refreshButton)refreshButton.disabled=true;
    try{
      const result=await api('/api/account/overview');
      if(sessionEpoch!==session||refreshEpoch!==revision)return;
      currentData=result;
      write('account-h1-state',result.h1cloud?.message||'H1Cloud не отвечает.');
      const emailStatus=$('account-email-status');
      if(emailStatus){
        emailStatus.textContent=result.email?.verified
          ?'Подтверждённая почта: '+result.email.address
          :'Почта не подтверждена. Для получения подписки её нужно подтвердить.';
      }
      hide('account-checkout-link',!result.email?.verified);
      hide('account-checkout-verify',!!result.email?.verified);
      const orders=Array.isArray(result.orders)?result.orders.filter(order=>order&&typeof order==='object'):[];
      historyOrders=orders;
      write('account-history-count',String(orders.length));
      showHistory();
      const delivery=result.subscription;
      const paidReady=delivery?.status==='delivered'&&delivery?.paid===true;
      const giftedReady=delivery?.status==='issued'&&
        delivery?.gifted===true&&delivery?.paid===false;
      const ready=paidReady||giftedReady;
      updateTraffic(ready?delivery:null);
      renderAdvisories(result);
      if(ready){
        write('metric-plan',delivery.plan_title||'VPN-подписка');
        write('metric-expiry',formatDate(delivery.expires_at));
        updateExpiryNote(delivery.expires_at);
        write('metric-devices',String(delivery.device_limit||'—'));
        write('account-plan-name',delivery.plan_title||'Активный тариф');
        write('account-plan-chip',giftedReady
          ?'Выдано оператором · без оплаты':'Оплачено · доступ выдан');
        write('account-plan-sub',delivery.expires_at
          ?'Подписка до '+formatDate(delivery.expires_at)
          :'Точный срок проверь в H1Cloud');
        write('account-device-limit',String(delivery.device_limit||'—')+' устройства');
        write('account-device-note','Максимальное число устройств по действующему тарифу.');
        write('account-plan-price',giftedReady?'Без оплаты':'Смотри в заказе');
        write('account-access-status',giftedReady
          ?'Ручная подписка активна. Можно получить персональную ссылку и открыть её в Happ или INCY.'
          :'Доступ выдан. Личную ссылку можно открыть или скопировать.');
        const get=$('account-get-vpn');
        if(get){
          get.disabled=false;
          // Fetch the subscription on the verified dashboard only. Direct links
          // then open immediately from a user's click without an async browser popup.
          if(!subscriptionUrl)get.click();
        }
        const qrButton=$('account-get-qr');
        if(qrButton)qrButton.disabled=!paidReady;
      }else if(delivery?.paid===true&&delivery?.status==='verification_pending'){
        write('metric-plan',delivery.plan_title||'Оплаченная подписка');
        write('metric-expiry','Проверяется');
        write('metric-devices',String(delivery.device_limit||'—'));
        write('account-plan-name',delivery.plan_title||'Оплаченный тариф');
        write('account-plan-chip','Выдача подтверждена · проверяем H1Cloud');
        write('account-plan-sub','Провайдер пока не подтвердил активность. Не оплачивай повторно.');
        write('account-device-limit',String(delivery.device_limit||'—'));
        write('account-device-note','Лимит по оплаченному тарифу, не статус подключения.');
        write('account-access-status','Заказ оплачен, но активный VPN-профиль не подтверждён. Повтори проверку позже.');
      }
      const manual=result.manual_grant;
      if(manual?.status==='unavailable'){
        write('account-manual-status','Временная ошибка проверки ручной выдачи. Оплаченные данные сохранены.');
      }else if(manual?.available===true){
        write('account-manual-status','Подписка от оператора активна до '+
          formatDate(manual.expires_at)+'. Разрешено устройств: '+manual.devices+
          '. Нажми «Проверить подписку», чтобы получить отдельную ссылку.');
      }else{
        write('account-manual-status','Активной ручной подписки для подтверждённого email нет.');
      }
      updatePrivateActions();
      const moment=new Intl.DateTimeFormat('ru-RU',{hour:'2-digit',minute:'2-digit'}).format(new Date());
      setAccountHealth('Данные кабинета проверены в '+moment+
        '. Состояние VPN-туннеля проверяй непосредственно в Happ или INCY.','verified');
    }catch(error){
      if(sessionEpoch!==session||refreshEpoch!==revision)return;
      setAccountHealth(navigator.onLine===false
        ?'Нет интернета. Данные не обновлены; повтори проверку после восстановления связи.'
        :'Не удалось обновить кабинет. Сведения о подписке сейчас не подтверждены — попробуй ещё раз.','error');
      write('account-h1-state','Не удалось загрузить кабинет: '+error.message);
      const history=$('account-order-list');
      if(history)history.textContent='Не удалось получить историю покупок. Нажми «Обновить данные».';
      write('account-history-match','История пока недоступна.');
      write('account-history-hint','Сервер не подтвердил состояние заказов. Попробуй обновить кабинет.');
    }finally{
      if(refreshButton&&sessionEpoch===session&&refreshEpoch===revision)refreshButton.disabled=false;
    }
  }
  async function refreshTestSubscriptions(session,revision){
    const list=$('account-test-vpn-list');
    if(!list)return;
    try{
      const result=await api('/api/account/test-subscriptions');
      if(sessionEpoch!==session||refreshEpoch!==revision)return;
      list.replaceChildren();
      const orders=Array.isArray(result.items)?result.items:[];
      hide('account-test-vpn',!orders.length);
      for(const order of orders){
        if(order.sandbox_only!==true||order.test_payment!==true)continue;
        const row=document.createElement('p');
        const title=document.createElement('span');
        const deliveryLabels={
          pending:'Ожидает выдачи',claimed:'Выдача обрабатывается',
          issued:'Выдан',needs_review:'Нужна проверка выдачи',
          failed_before_write:'Выдача временно недоступна',not_issued:'Ожидает выдачи'
        };
        title.textContent='Тестовый VPN · '+order.title+' · '+order.device_limit+' устройств · '+
          (deliveryLabels[order.delivery_state]||'Состояние выдачи неизвестно');
        row.append(title);
        if(order.vpn_delivered===true){
          const button=document.createElement('button');
          button.type='button';button.className='account-secondary-link';
          button.textContent='Получить личную ссылку';
          button.addEventListener('click',async()=>{
            if(sessionEpoch!==session||refreshEpoch!==revision)return;
            button.disabled=true;
            try{
              const access=await api('/api/shop/my-test-orders/'+encodeURIComponent(order.order_id)+'/vpn-access');
              if(sessionEpoch!==session||refreshEpoch!==revision)return;
              const url=new URL(access.subscription_url);
              if(url.protocol!=='https:'||url.username||url.password||url.hash)throw Error('INVALID_LINK');
              const link=document.createElement('a');
              link.href=url.href;link.referrerPolicy='no-referrer';
              link.textContent='Открыть личную тестовую подписку';
              button.replaceWith(link);
            }catch{
              if(sessionEpoch!==session||refreshEpoch!==revision)return;
              button.textContent='Не удалось получить ссылку. Повторить';
              button.disabled=false;
            }
          });
          row.append(document.createTextNode(' · '),button);
        }
        list.append(row);
      }
    }catch{
      if(sessionEpoch!==session||refreshEpoch!==revision)return;
      hide('account-test-vpn',false);
      list.textContent='Не удалось загрузить тестовые подписки. Обнови кабинет.';
    }
  }
  const getQR=$('account-get-qr');
  if(getQR)getQR.addEventListener('click',async()=>{
    if(!user||!currentData?.subscription?.paid||
        currentData?.subscription?.status!=='delivered')return;
    if(privateQrUrl){
      clearQR();
      return;
    }
    if(qrPending)return;
    const session=sessionEpoch,revision=refreshEpoch;
    qrPending=true;getQR.disabled=true;
    hide('account-qr-panel',false);
    write('account-qr-status','Создаём QR-код только для твоей подтверждённой подписки…');
    try{
      const response=await fetch('/api/account/qr',{
        method:'GET',credentials:'same-origin',cache:'no-store',
        headers:{Accept:'image/svg+xml'}
      });
      if(!response.ok)throw Error('Сервер не подтвердил доступ ('+response.status+').');
      const mime=response.headers?.get('content-type')||'';
      if(!mime.startsWith('image/svg+xml'))throw Error('Некорректный формат QR-кода.');
      const blob=await response.blob();
      if(blob.size<100||blob.size>2_000_000)throw Error('Некорректный размер QR-кода.');
      if(session!==sessionEpoch||revision!==refreshEpoch)return;
      const image=$('account-qr-image');
      if(!image)throw Error('Не найден элемент для QR-кода.');
      privateQrUrl=URL.createObjectURL(blob);
      image.src=privateQrUrl;
      image.hidden=false;
      getQR.textContent='Скрыть QR-код';
      write('account-qr-status','Готово. Используй QR только на своём устройстве. Закрой его после подключения.');
    }catch(error){
      if(session===sessionEpoch&&revision===refreshEpoch){
        write('account-qr-status','QR недоступен: '+(error.message||'ошибка')+
          ' Обычная VPN-ссылка остаётся доступной.');
      }
    }finally{
      qrPending=false;
      if(session===sessionEpoch&&revision===refreshEpoch)getQR.disabled=false;
    }
  });
  if(window.addEventListener){
    window.addEventListener('pagehide',()=>{
      // The browser may keep this page in BFCache when opening an external app.
      // Do not leave a previously verified private URL in its retained DOM.
      ++refreshEpoch;
      clearSubscription();
      currentData=null;
      clearQR();
    });
    window.addEventListener('pageshow',event=>{
      if(event?.persisted&&user)void refresh();
    });
    window.addEventListener('online',()=>{
      if(user&&!currentData)void refresh();
    });
  }
  const get=$('account-get-vpn');
  if(get)get.addEventListener('click',async()=>{
    const subscription=currentData?.subscription;
    const paid=subscription?.paid===true&&subscription?.status==='delivered'&&
      !!subscription?.order_id;
    const gifted=subscription?.paid===false&&subscription?.gifted===true&&
      subscription?.status==='issued';
    if(!user||(!paid&&!gifted))return;
    const session=sessionEpoch;
    const revision=refreshEpoch;
    get.disabled=true;
    try{
      const response=await api(gifted?'/api/account/manual-grant':'/api/account/access');
      if(sessionEpoch!==session||refreshEpoch!==revision)return;
      if(gifted&&response.available!==true)throw Error('MANUAL_GRANT_NOT_ACTIVE');
      const url=new URL(response.subscription_url);
      if(url.protocol!=='https:'||url.username||url.password||url.hash)throw Error('INVALID_LINK');
      subscriptionUrl=url.href;
      if(gifted){
        manualGrantUrl=subscriptionUrl;
        hide('account-manual-copy',false);
        updateClientLinks(manualGrantUrl,true);
      }
      const open=$('account-open-vpn');
      if(open){open.href=subscriptionUrl;open.referrerPolicy='no-referrer';open.hidden=false;}
      // Direct user-clicked custom schemes; never put the private URL in
      // site navigation, query parameters, analytics or app download links.
      updateClientLinks(subscriptionUrl);
      hide('account-copy-vpn',false);
      const copy=$('account-copy-vpn');if(copy)copy.disabled=false;
      write('account-access-status',gifted
        ?'Ручная подписка подтверждена. Выбери Happ или INCY. Никому не передавай свой ключ.'
        :'Ссылка готова. Выбери Happ или INCY для импорта. Никому не передавай свой ключ.');
    }catch(error){
      if(sessionEpoch!==session||refreshEpoch!==revision)return;
      write('account-access-status','Не удалось получить ссылку: '+error.message);
    }
    finally{if(sessionEpoch===session&&refreshEpoch===revision)get.disabled=false;}
  });
  const copy=$('account-copy-vpn');
  if(copy)copy.addEventListener('click',async()=>{
    if(!subscriptionUrl)return;
    const session=sessionEpoch;
    const revision=refreshEpoch;
    try{
      await navigator.clipboard.writeText(subscriptionUrl);
      if(sessionEpoch!==session||refreshEpoch!==revision)return;
      write('account-access-status','Личная ссылка скопирована.');
    }catch{
      if(sessionEpoch===session&&refreshEpoch===revision)write('account-access-status','Не удалось скопировать ссылку.');
    }
  });
  const manualGet=$('account-manual-get');
  if(manualGet)manualGet.addEventListener('click',async()=>{
    if(!user)return;
    const session=sessionEpoch,revision=refreshEpoch;
    manualGet.disabled=true;
    write('account-manual-status','Проверяем персональную выдачу в H1Cloud...');
    try{
      const result=await api('/api/account/manual-grant');
      if(session!==sessionEpoch||revision!==refreshEpoch)return;
      if(result.available!==true){
        write('account-manual-status','Для этой подтверждённой почты нет активной ручной подписки.');
        return;
      }
      const url=new URL(result.subscription_url);
      if(url.protocol!=='https:'||url.username||url.password||url.hash)throw Error('INVALID_LINK');
      manualGrantUrl=url.href;
      hide('account-manual-copy',false);
      updateClientLinks(manualGrantUrl,true);
      write('account-manual-status','Подписка без оплаты активна до '+
        formatDate(result.expires_at)+'. Устройств: '+result.devices+'.');
    }catch(error){
      if(session===sessionEpoch&&revision===refreshEpoch)
        write('account-manual-status','Не удалось проверить подписку: '+error.message);
    }finally{
      if(session===sessionEpoch&&revision===refreshEpoch)manualGet.disabled=false;
    }
  });
  const manualCopy=$('account-manual-copy');
  if(manualCopy)manualCopy.addEventListener('click',async()=>{
    if(!manualGrantUrl)return;
    try{
      await navigator.clipboard.writeText(manualGrantUrl);
      write('account-manual-status','Личная ссылка скопирована. Не отправляй её посторонним.');
    }catch{write('account-manual-status','Браузер запретил копирование ссылки.');}
  });
  for(const [id,client,manual] of [
    ['account-open-happ','happ',false],
    ['account-open-incy','incy',false],
    ['account-manual-happ','happ',true],
    ['account-manual-incy','incy',true],
  ])registerImportFallback(id,client,manual);
  const logout=$('account-exit');
  if(logout)logout.addEventListener('click',async()=>{
    // Clear private links immediately, even while the logout request is pending.
    showSession(null);
    const session=sessionEpoch;
    try{
      await api('/api/email-auth/logout',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({})
      });
    }catch{
      if(sessionEpoch===session)write('account-auth-status','Не удалось завершить выход. Повтори попытку.');
    }
  });
  function downloadCalendar(){
    const date=validExpiry(currentData?.subscription?.expires_at);
    if(!user||!date||currentData?.subscription?.paid!==true||
       currentData?.subscription?.status!=='delivered')return;
    const icsDate=d=>d.toISOString().replace(/[-:]/g,'').replace(/\.\d{3}Z$/,'Z');
    // A real calendar alarm is needed: merely creating an event does not
    // guarantee the user will receive a reminder.
    const alarms=[
      ['-P7D','за 7 дней'],['-P3D','за 3 дня'],['-P1D','за 1 день']
    ].flatMap(([trigger,label])=>[
      'BEGIN:VALARM','ACTION:DISPLAY','TRIGGER:'+trigger,
      'DESCRIPTION:Проверь подписку Vainah VPN ('+label+').',
      'END:VALARM'
    ]);
    const content=[
      'BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Vainah VPN//Subscription Reminder//RU',
      'CALSCALE:GREGORIAN','METHOD:PUBLISH',
      'BEGIN:VEVENT',
      'UID:vainah-renewal-'+icsDate(date)+'@reminder.invalid',
      'DTSTAMP:'+icsDate(new Date()),
      'DTSTART:'+icsDate(date),
      'DTEND:'+icsDate(new Date(date.getTime()+900000)),
      'SUMMARY:Проверить продление Vainah VPN',
      'DESCRIPTION:Проверь состояние подписки в личном кабинете Vainah VPN. Ссылка и платёжные данные не включены.',
      ...alarms,
      'END:VEVENT','END:VCALENDAR',''
    ].join('\r\n');
    try{
      const url=URL.createObjectURL(new Blob([content],{type:'text/calendar;charset=utf-8'}));
      const link=document.createElement('a');
      link.href=url;link.download='vainah-vpn-reminder.ics';
      link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
      write('account-calendar-status','Календарь создан: напоминания за 7, 3 и 1 день. Импортируй файл в календарь и разреши уведомления.');
    }catch{
      write('account-calendar-status','Не удалось скачать календарный файл. Проверь разрешения браузера.');
    }
  }
  function safeSupportReport(){
    if(!user||!currentData)return;
    const sub=currentData.subscription;
    const orders=Array.isArray(currentData.orders)?currentData.orders:[];
    const status=typeof currentData.h1cloud?.status==='string'&&
      ['active','inactive','not_found','not_configured','unavailable'].includes(currentData.h1cloud.status)
      ?currentData.h1cloud.status:'unknown';
    const text=[
      'VAINAH VPN — сведения для поддержки',
      'Вход выполнен: да',
      'Оплаченная подписка: '+(sub?.paid===true&&sub?.status==='delivered'?'подтверждена':'не подтверждена'),
      'Ручная подписка: '+(sub?.gifted===true&&sub?.status==='issued'?'подтверждена':'не подтверждена'),
      'Состояние H1Cloud: '+status,
      'Заказов в истории: '+orders.length,
      'Дата окончания: '+((sub?.paid===true&&sub?.status==='delivered')||
        (sub?.gifted===true&&sub?.status==='issued')?formatDate(sub.expires_at):'не подтверждена'),
      'VPN-ключи, email, ID заказа и платёжные реквизиты исключены.'
    ].join('\n');
    return text;
  }
  const calendarButton=$('account-calendar');
  if(calendarButton)calendarButton.addEventListener('click',downloadCalendar);
  const supportButton=$('account-support-summary');
  if(supportButton)supportButton.addEventListener('click',async()=>{
    const report=safeSupportReport();if(!report)return;
    const session=sessionEpoch,revision=refreshEpoch;
    try{
      if(!navigator.clipboard?.writeText)throw Error('CLIPBOARD_UNAVAILABLE');
      await navigator.clipboard.writeText(report);
      if(session===sessionEpoch&&revision===refreshEpoch)
        write('account-calendar-status','Безопасный статус скопирован для обращения в поддержку.');
    }catch{
      if(session!==sessionEpoch||revision!==refreshEpoch)return;
      const manual=$('account-support-manual');
      if(manual){manual.hidden=false;manual.value=report;manual.focus();manual.select();}
      write('account-calendar-status','Браузер запретил копирование. Выделенный текст можно скопировать вручную.');
    }
  });
  const refreshButton=$('account-refresh');
  if(refreshButton)refreshButton.addEventListener('click',refresh);
  for(const id of ['account-order-search','account-order-filter','account-order-sort']){
    const control=$(id);
    if(control)control.addEventListener(id==='account-order-search'?'input':'change',showHistory);
  }
  const exportButton=$('account-order-export');
  if(exportButton)exportButton.addEventListener('click',exportHistory);
  const form=$('account-email-form');
  if(form)form.addEventListener('submit',async(event)=>{
    event.preventDefault();
    if(!user)return;
    const session=sessionEpoch;
    const email=$('account-email-input')?.value?.trim();
    if(!email)return;
    const button=form.querySelector('button[type="submit"]');
    button.disabled=true;
    try{
      await api('/api/account/email/request',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({email})
      });
      if(sessionEpoch!==session)return;
      hide('account-email-verify',false);
      write('account-email-status','Код отправлен на почту. Введи его для подтверждения.');
    }catch(error){
      if(sessionEpoch===session)write('account-email-status','Не удалось отправить код: '+error.message);
    }
    finally{button.disabled=false;}
  });
  const verifyForm=$('account-email-verify');
  if(verifyForm)verifyForm.addEventListener('submit',async(event)=>{
    event.preventDefault();
    if(!user)return;
    const session=sessionEpoch;
    const code=$('account-email-code')?.value?.trim();
    if(!code)return;
    const button=verifyForm.querySelector('button[type="submit"]');
    button.disabled=true;
    try{
      const email=await api('/api/account/email/confirm',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({code})
      });
      if(sessionEpoch!==session)return;
      write('account-email-status','Адрес подтверждён: '+email.email);
      hide('account-email-verify',true);
      await refresh();
    }catch(error){
      if(sessionEpoch===session)write('account-email-status','Не удалось подтвердить почту: '+error.message);
    }
    finally{button.disabled=false;}
  });
  async function resumeSession(){
    const session=sessionEpoch;
    // Email purchases and operator grants are tied to verified mailboxes.
    // Prefer a valid email session when both legacy cookies are present.
    try{
      const email=await api('/api/email-auth/account');
      if(sessionEpoch!==session)return;
      if(email.authenticated&&email.user){
        showSession(email.user);
        return;
      }
    }catch{ /* Telegram can still restore independently. */ }
    if(sessionEpoch!==session)return;
    try{
      const tg=await api('/api/telegram/account');
      if(sessionEpoch!==session)return;
      if(tg.authenticated&&tg.user){
        showSession({...tg.user,auth_method:'telegram'});
        return;
      }
    }catch{ /* No active Telegram session. */ }
    if(sessionEpoch===session)showSession(null);
  }
  // Fail closed before the first async authentication check resolves.
  updatePrivateActions();
  void resumeSession();
})();
