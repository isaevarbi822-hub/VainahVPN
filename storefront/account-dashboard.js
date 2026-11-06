/* Verified Telegram and email dashboard. Never fabricate subscriptions. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const write=(id,value)=>{const node=$(id);if(node)node.textContent=value;};
  const hide=(id,value)=>{const node=$(id);if(node)node.hidden=value;};
  let user=null;
  let subscriptionUrl=null;
  let currentData=null;
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
  function renderOrders(orders){
    const history=$('account-order-list');
    if(!history)return;
    history.replaceChildren();
    if(!orders.length){
      const empty=document.createElement('div');
      empty.className='account-empty';
      const heading=document.createElement('strong');
      heading.textContent='Пока нет заказов';
      const detail=document.createElement('span');
      detail.textContent='Начни с пробного периода или выбери тариф.';
      const actions=document.createElement('div');
      actions.className='account-empty-actions';
      for(const [href,label] of [['trial.html','Пробный доступ'],['plans.html','Выбрать тариф']]){
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
      const orders=Array.isArray(result.orders)?result.orders:[];
      write('account-history-count',String(orders.length));
      renderOrders(orders);
      const delivery=result.subscription;
      const ready=delivery?.status==='delivered'&&delivery?.paid===true;
      updateTraffic(ready?delivery:null);
      if(ready){
        write('metric-plan',delivery.plan_title||'VPN-подписка');
        write('metric-expiry',formatDate(delivery.expires_at));
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
    }catch(error){
      if(sessionEpoch!==session||refreshEpoch!==revision)return;
      write('account-h1-state','Не удалось загрузить кабинет: '+error.message);
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
  const refreshButton=$('account-refresh');
  if(refreshButton)refreshButton.addEventListener('click',refresh);
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
