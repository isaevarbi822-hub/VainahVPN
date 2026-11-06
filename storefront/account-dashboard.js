/* Verified Telegram and email dashboard. Never fabricate subscriptions. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const write=(id,value)=>{const node=$(id);if(node)node.textContent=value;};
  const hide=(id,value)=>{const node=$(id);if(node)node.hidden=value;};
  let user=null;
  let subscriptionUrl=null;
  let currentData=null;
  let historyOrders=[];
  let sessionEpoch=0;
  let refreshEpoch=0;
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
  const safeString=value=>typeof value==='string'?value:'';
  function formatDate(value){
    if(!value)return 'Не указана';
    const date=new Date(value);
    if(Number.isNaN(date.getTime()))return 'Не указана';
    return new Intl.DateTimeFormat('ru-RU',{day:'2-digit',month:'short',year:'numeric'}).format(date);
  }
  const statusNames={
    delivered:'Оплачено · выдано',paid:'Оплачено · выдаётся',
    pending:'Ожидает оплаты',created:'Ожидает оплаты',
    processing:'Обрабатывается',cancelled:'Отменён',canceled:'Отменён',
    expired:'Истёк',failed:'Ошибка обработки',
    needs_review:'Требуется проверка',
    refund:'Возврат',refunded:'Возврат'
  };
  function orderStatus(value){
    return statusNames[safeString(value)]||'Статус уточняется';
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
      const status=safeString(order.status);
      if(filter==='delivered'&&status!=='delivered')return false;
      if(filter==='waiting'&&!['created','pending','paid','processing','needs_review'].includes(status))return false;
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
        orderStatus(order.status)
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
      // Overview intentionally does not send a verified monetary total.
      amount.textContent='—';
      amount.title='Сумма не предоставлена сервером';
      const state=document.createElement('div');
      state.className='order-state '+statusClass(order.status);
      state.textContent=orderStatus(order.status);
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
  function clearSubscription(){
    subscriptionUrl=null;
    const open=$('account-open-vpn');
    if(open)open.removeAttribute('href');
    hide('account-open-vpn',true);
    hide('account-copy-vpn',true);
    const copy=$('account-copy-vpn');
    if(copy)copy.disabled=true;
    const get=$('account-get-vpn');
    if(get)get.disabled=true;
    updateTraffic(null);
    updateExpiryNote(null);
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
    write('account-history-hint','В истории отображаются только подтверждённые покупки.');
    const history=$('account-order-list');
    if(history)history.textContent='Пока нет подтверждённых покупок.';
  }
  function showSession(next){
    sessionEpoch++;
    user=next||null;resetPrivate();
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
      const orders=Array.isArray(result.orders)?result.orders.filter(order=>order&&typeof order==='object'):[];
      historyOrders=orders;
      write('account-history-count',String(orders.length));
      showHistory();
      const delivery=result.subscription;
      const ready=delivery?.status==='delivered'&&delivery?.paid===true;
      updateTraffic(ready?delivery:null);
      if(ready){
        write('metric-plan',delivery.plan_title||'VPN-подписка');
        write('metric-expiry',formatDate(delivery.expires_at));
        updateExpiryNote(delivery.expires_at);
        write('metric-devices',String(delivery.device_limit||'—'));
        write('account-plan-name',delivery.plan_title||'Активный тариф');
        write('account-plan-chip','Оплачено · доступ выдан');
        write('account-plan-sub',delivery.expires_at
          ?'Подписка до '+formatDate(delivery.expires_at)
          :'Точный срок проверь в H1Cloud');
        write('account-device-limit',String(delivery.device_limit||'—')+' устройства');
        write('account-device-note','Максимальное число устройств по действующему тарифу.');
        write('account-plan-price','Смотри в заказе');
        write('account-access-status','Доступ доступен. Личную ссылку можно открыть или скопировать.');
        const get=$('account-get-vpn');if(get)get.disabled=false;
      }
      updatePrivateActions();
    }catch(error){
      if(sessionEpoch!==session||refreshEpoch!==revision)return;
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
  const get=$('account-get-vpn');
  if(get)get.addEventListener('click',async()=>{
    if(!user||!currentData?.subscription?.order_id)return;
    const session=sessionEpoch;
    const revision=refreshEpoch;
    get.disabled=true;
    try{
      const response=await api('/api/account/access');
      if(sessionEpoch!==session||refreshEpoch!==revision)return;
      const url=new URL(response.subscription_url);
      if(url.protocol!=='https:'||url.username||url.password)throw Error('INVALID_LINK');
      subscriptionUrl=url.href;
      const open=$('account-open-vpn');
      if(open){open.href=subscriptionUrl;open.referrerPolicy='no-referrer';open.hidden=false;}
      hide('account-copy-vpn',false);
      const copy=$('account-copy-vpn');if(copy)copy.disabled=false;
      write('account-access-status','Ссылка готова. Никому не передавай свой ключ.');
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
    const reminder=new Date(date.getTime()-86400000);
    const icsDate=d=>d.toISOString().replace(/[-:]/g,'').replace(/\.\d{3}Z$/,'Z');
    const content=[
      'BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Vainah VPN//Subscription Reminder//RU',
      'CALSCALE:GREGORIAN','METHOD:PUBLISH',
      'BEGIN:VEVENT',
      'UID:vainah-renewal-'+icsDate(date)+'@reminder.invalid',
      'DTSTAMP:'+icsDate(new Date()),
      'DTSTART:'+icsDate(reminder),
      'DTEND:'+icsDate(new Date(reminder.getTime()+900000)),
      'SUMMARY:Проверить продление Vainah VPN',
      'DESCRIPTION:Проверь состояние подписки в личном кабинете Vainah VPN. Ссылка и платёжные данные не включены.',
      'END:VEVENT','END:VCALENDAR',''
    ].join('\r\n');
    try{
      const url=URL.createObjectURL(new Blob([content],{type:'text/calendar;charset=utf-8'}));
      const link=document.createElement('a');
      link.href=url;link.download='vainah-vpn-reminder.ics';
      link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
      write('account-calendar-status','Календарный файл создан. Открой его и сохрани событие, чтобы получить напоминание.');
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
      'Подтверждённая подписка: '+(sub?.paid===true&&sub?.status==='delivered'?'да':'не подтверждена'),
      'Состояние H1Cloud: '+status,
      'Заказов в истории: '+orders.length,
      'Дата окончания: '+(sub?.paid===true&&sub?.status==='delivered'?formatDate(sub.expires_at):'не подтверждена'),
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
    try{
      const tg=await api('/api/telegram/account');
      if(sessionEpoch!==session)return;
      if(tg.authenticated&&tg.user){
        showSession({...tg.user,auth_method:'telegram'});
        return;
      }
    }catch{ /* Email is independent of Telegram availability. */ }
    if(sessionEpoch!==session)return;
    try{
      const email=await api('/api/email-auth/account');
      if(sessionEpoch!==session)return;
      if(email.authenticated&&email.user){
        showSession(email.user);
        return;
      }
    }catch{ /* No active email session. */ }
    if(sessionEpoch===session)showSession(null);
  }
  void resumeSession();
})();
