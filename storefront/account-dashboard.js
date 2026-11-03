/* Vainah VPN dashboard. Real records only; all customer text rendered safely. */
(function(){
  'use strict';
  const $=id=>document.getElementById(id);
  const api='/.netlify/functions/';
  const el={
    login:$('account-auth-panel'),private:$('account-private'),
    altPrivate:$('account-alt-private'),altProvider:$('account-alt-provider'),altExit:$('account-alt-exit'),
    auth:$('account-auth-status'),widget:$('account-widget'),
    user:$('account-user'),avatar:$('account-avatar'),logout:$('account-exit'),
    plan:$('metric-plan'),expiry:$('metric-expiry'),devices:$('metric-devices'),
    planName:$('account-plan-name'),planSub:$('account-plan-sub'),
    planPrice:$('account-plan-price'),chip:$('account-plan-chip'),
    accessStatus:$('account-access-status'),getVpn:$('account-get-vpn'),
    openVpn:$('account-open-vpn'),copyVpn:$('account-copy-vpn'),
    deviceLimit:$('account-device-limit'),deviceNote:$('account-device-note'),
    h1:$('account-h1-state'),history:$('account-order-list'),
    historyCount:$('account-history-count'),historyHint:$('account-history-hint'),
    refresh:$('account-refresh')
  };
  let user=null,overview=null,vpnUrl=null,epoch=0,loginAttempt=0;
  const uuid=/^[a-f0-9]{8}-[a-f0-9-]{27,36}$/i;
  const rub=(value)=>Number.isFinite(Number(value))?new Intl.NumberFormat('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(value))+' ₽':'—';
  const date=(value)=>{
    if(!value)return '—';
    const d=new Date(value);
    return Number.isFinite(d.getTime())?d.toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'}):'—';
  };
  const planName=(days,deviceLimit)=>deviceLimit===6&&days===365?'Семейный · 1 год':
    ({30:'1 месяц',60:'2 месяца',90:'3 месяца',180:'6 месяцев',365:'1 год'}[days]||days+' дней');
  async function request(path,options={}){
    const response=await fetch(api+path,{
      credentials:'same-origin',cache:'no-store',
      headers:{Accept:'application/json',...(options.headers||{})},...options
    });
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(typeof data.error==='string'?data.error:'Ошибка сервера ('+response.status+')');
    return data;
  }
  function node(tag,klass,text){
    const n=document.createElement(tag);
    if(klass)n.className=klass;
    if(text!==undefined)n.textContent=String(text);
    return n;
  }
  function statusLabel(o){
    if(o.status==='paid'){
      if(o.deliveryState==='delivered')return {text:'Оплачено · доступ выдан',kind:'success'};
      if(o.deliveryState==='needs_review')return {text:'Нужна проверка',kind:'error'};
      if(o.deliveryState==='retry')return {text:'Оплачено · выдача задержана',kind:'pending'};
      return {text:'Оплачено · готовим VPN',kind:'pending'};
    }
    const states={
      created:['Счёт создаётся','pending'],
      awaiting_payment:['Ожидает оплаты','pending'],
      canceled:['Отменён','error'],
      expired:['Счёт истёк','error'],
      refunded:['Возврат','error'],
      chargeback:['Платёж оспорен','error'],
      error:['Не удалось создать счёт','error']
    };
    const [text,kind]=states[o.status]||['Обрабатывается','pending'];
    return {text,kind};
  }
  function clearVpnLink(){
    vpnUrl=null;
    el.openVpn.hidden=true;el.openVpn.removeAttribute('href');
    el.copyVpn.hidden=true;
  }
  function showSession(nextUser){
    user=nextUser||null;
    epoch++;
    overview=null;
    clearVpnLink();
    el.plan.textContent='Загружаем…';el.expiry.textContent='—';el.devices.textContent='—';
    el.planName.textContent='Загружаем…';el.planSub.textContent='Проверяем покупки';
    el.planPrice.textContent='—';el.historyCount.textContent='0';
    el.deviceLimit.textContent='—';el.getVpn.disabled=true;
    el.login.hidden=!!user;
    el.private.hidden=!user;
    el.altPrivate.hidden=true;
    el.logout.hidden=!user;
    el.user.textContent=user?(user.username?'@'+user.username:'Telegram ID '+user.telegramId):'Гость';
    el.avatar.textContent=user?(user.firstName||user.username||'T').slice(0,1).toUpperCase():'V';
    if(!user){
      el.auth.textContent='Войди через Telegram, чтобы открыть личный кабинет.';
      el.history.replaceChildren();
      el.getVpn.disabled=true;
    }
  }
  function showAlternateSession(session){
    const labels={phone:'Мобильный телефон',email:'Электронная почта',yandex:'Яндекс ID'};
    if(!session||!Object.prototype.hasOwnProperty.call(labels,session.provider))return;
    showSession(null);
    el.login.hidden=true;
    el.altPrivate.hidden=false;
    el.user.textContent='Подтверждённый вход';
    el.avatar.textContent=session.provider==='yandex'?'Я':session.provider==='email'?'@':'☎';
    el.altProvider.textContent='Способ авторизации: '+labels[session.provider]+'.';
  }
  window.onVainahAltLogin=async function(){
    loginAttempt++;
    const current=loginAttempt;
    try{
      const result=await request('alternate-login');
      if(current!==loginAttempt)return;
      if(result.authenticated&&result.user)showAlternateSession(result.user);
      else throw Error('Сервер не подтвердил вход');
    }catch(error){
      if(current===loginAttempt)el.auth.textContent='Ошибка подтверждения: '+error.message;
    }
  };
  el.altExit.addEventListener('click',async()=>{
    loginAttempt++;el.altExit.disabled=true;
    try{
      await request('alternate-login',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({action:'logout'})});
      showSession(null);
    }catch(error){el.altProvider.textContent='Не удалось выйти: '+error.message}
    finally{el.altExit.disabled=false}
  });
  function renderOverview(data){
    overview=data;
    const subscription=data.subscription;
    el.historyCount.textContent=String(data.orders.length);
    el.historyHint.textContent=data.historyLimited?'Показаны последние 30 заказов.':'Здесь только покупки через сайт Vainah VPN.';
    el.history.replaceChildren();
    if(!data.orders.length){
      const empty=node('div','account-empty');
      empty.append(node('strong','', 'Пока нет покупок на сайте'),
        node('span','', 'После оформления здесь появятся твои заказы и их статусы.'));
      const choose=node('a','account-secondary-link','Посмотреть тарифы →');choose.href='plans.html';
      empty.append(document.createElement('br'),choose);
      el.history.append(empty);
    }else{
      for(const order of data.orders){
        const row=node('article','account-order');
        const plan=node('div','');
        plan.append(node('div','order-name',planName(order.days,order.deviceLimit)),
          node('div','order-sub',order.deviceLimit+' устройств · '+order.days+' дней'));
        const when=node('div','order-sub',date(order.createdAt));
        const amount=node('div','order-amount',rub(order.amountRub));
        const stateInfo=statusLabel(order);
        const state=node('div','');
        state.append(node('span','order-state '+stateInfo.kind,stateInfo.text));
        if(uuid.test(order.id)){
          const a=node('a','order-more','Подробнее →');
          a.href='payment-result.html?order='+encodeURIComponent(order.id);
          state.append(document.createElement('br'),a);
        }
        row.append(plan,when,amount,state);
        el.history.append(row);
      }
    }
    clearVpnLink();
    if(!subscription){
      el.plan.textContent='Нет покупок';
      el.expiry.textContent='—';
      el.devices.textContent='—';
      el.planName.textContent='Твоя следующая подписка';
      el.planSub.textContent='После подтверждённой оплаты тариф появится здесь автоматически.';
      el.planPrice.textContent='—';
      el.chip.textContent='Нет активных покупок на сайте';
      el.chip.className='account-chip dim';
      el.deviceLimit.textContent='—';
      el.deviceNote.textContent='Доступный лимит устройств появится после покупки. Количество подключённых устройств сейчас не отслеживается.';
      el.accessStatus.textContent='Пока нет выданной подписки с сайта. Посмотри тарифы, чтобы выбрать подходящий.';
      el.getVpn.disabled=true;
      return;
    }
    const valid=subscription.active;
    const last=data.orders.find(o=>o.id===subscription.accessOrderId);
    const label=planName(subscription.planDays,subscription.deviceLimit);
    el.plan.textContent=label;
    el.expiry.textContent=date(subscription.expiresAt);
    el.devices.textContent=String(subscription.deviceLimit)+' устройств';
    el.planName.textContent=label;
    el.planSub.textContent='Тариф на '+subscription.planDays+' дней · '+subscription.deviceLimit+' устройств · безлимитный трафик';
    el.planPrice.textContent=last?rub(last.amountRub):'—';
    el.chip.textContent=valid?'Учтено в базе':'Срок в базе истёк';
    el.chip.className='account-chip '+(valid?'good':'warn');
    el.deviceLimit.textContent=String(subscription.deviceLimit)+' устройств';
    el.deviceNote.textContent='Это лимит тарифа, а не число подключённых устройств. Данные о подключениях пока не доступны.';
    el.accessStatus.textContent=valid?
      'Оплата подтверждена, заказ выдан. Чтобы получить персональную VPN-ссылку, нажми кнопку ниже. Фактический статус профиля проверяется отдельно по H1Cloud.':
      'Срок по записи в базе истёк. Если продлевал доступ через бота, его статус проверяй отдельно.';
    el.getVpn.disabled=!valid;
  }
  async function loadOrders(version){
    el.history.replaceChildren(node('div','account-empty','Загружаем историю покупок…'));
    try{
      const data=await request('website-account-overview');
      if(version!==epoch)return;
      if(!Array.isArray(data.orders))throw Error('Некорректный ответ сервера');
      renderOverview(data);
    }catch(error){
      if(version!==epoch)return;
      el.history.replaceChildren(node('div','account-empty','Не удалось загрузить историю: '+error.message));
      el.accessStatus.textContent='Не удалось проверить покупку. Обнови страницу позже.';
      el.getVpn.disabled=true;
    }
  }
  async function loadH1(version){
    el.h1.textContent='Проверяем профиль через H1Cloud…';
    try{
      const info=await request('my-subscription');
      if(version!==epoch)return;
      if(!info.panelReady)el.h1.textContent='H1Cloud пока не подключён к сайту.';
      else if(!info.found)el.h1.textContent='Профиль по Telegram ID в H1Cloud пока не найден.';
      else if(info.banned)el.h1.textContent='Профиль отключён. Обратись в поддержку.';
      else if(info.active)el.h1.textContent='H1Cloud подтверждает: профиль активен до '+date(info.expiresAt)+'.';
      else el.h1.textContent='H1Cloud: срок профиля истёк.';
    }catch{
      if(version===epoch)el.h1.textContent='Панель H1Cloud временно недоступна. Даты покупок выше взяты из PostgreSQL; состояние VPN пока не подтверждено.';
    }
  }
  async function refreshAll(){
    if(!user)return;
    const version=epoch;
    el.refresh.disabled=true;el.refresh.textContent='Обновляем…';
    await Promise.allSettled([loadOrders(version),loadH1(version)]);
    if(version===epoch){el.refresh.disabled=false;el.refresh.textContent='↻ Обновить данные'}
  }
  async function revealAccess(){
    const orderId=overview?.subscription?.accessOrderId;
    if(!user||!overview?.subscription?.active||!uuid.test(orderId||''))return;
    const version=epoch;
    el.getVpn.disabled=true;clearVpnLink();
    el.accessStatus.textContent='Получаем защищённую VPN-ссылку из H1Cloud…';
    try{
      const data=await request('website-vpn-access?order='+encodeURIComponent(orderId));
      if(version!==epoch)return;
      const url=new URL(data.subscriptionUrl);
      if(url.protocol!=='https:'||!url.hostname||url.username||url.password)throw Error('Некорректная VPN-ссылка');
      vpnUrl=data.subscriptionUrl;
      el.openVpn.href=vpnUrl;el.openVpn.referrerPolicy='no-referrer';
      el.openVpn.hidden=false;el.copyVpn.hidden=false;
      el.accessStatus.textContent='Ссылка готова. Не передавай её посторонним — она даёт доступ к твоему VPN.';
    }catch(error){
      if(version===epoch)el.accessStatus.textContent='Не удалось получить VPN-ссылку: '+error.message+'. Покупка остаётся в истории.';
    }finally{if(version===epoch)el.getVpn.disabled=false}
  }
  el.getVpn.addEventListener('click',revealAccess);
  el.copyVpn.addEventListener('click',async()=>{
    if(!vpnUrl)return;
    try{
      await navigator.clipboard.writeText(vpnUrl);
      el.accessStatus.textContent='VPN-ссылка скопирована. Не отправляй её посторонним.';
    }catch{el.accessStatus.textContent='Не удалось скопировать ссылку. Воспользуйся кнопкой «Открыть подписку».'}
  });
  el.refresh.addEventListener('click',refreshAll);
  el.logout.addEventListener('click',async()=>{
    loginAttempt++;
    el.logout.disabled=true;
    try{
      await request('telegram-account',{method:'POST',
        headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'logout'})});
      showSession(null);
    }catch(error){
      el.auth.textContent='Не удалось выйти: '+error.message;
    }finally{el.logout.disabled=false}
  });
  window.onVainahAccountAuth=async function(data){
    loginAttempt++;
    try{
      el.auth.textContent='Подтверждаем вход через Telegram…';
      const result=await request('telegram-account',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({action:'login',data})});
      showSession(result.user);
      refreshAll();
    }catch(error){
      el.auth.textContent='Ошибка входа: '+error.message;
    }
  };
  const initialAttempt=loginAttempt;
  request('telegram-account').then(async result=>{
    if(loginAttempt!==initialAttempt)return;
    if(result.user){
      showSession(result.user);
      refreshAll();
      return;
    }
    try{
      const alternate=await request('alternate-login');
      if(loginAttempt!==initialAttempt)return;
      if(alternate.authenticated&&alternate.user)showAlternateSession(alternate.user);
      else showSession(null);
    }catch{
      if(loginAttempt===initialAttempt)showSession(null);
    }
  }).catch(()=>{
    if(loginAttempt!==initialAttempt)return;
    showSession(null);
    el.auth.textContent='Не получилось проверить вход. Проверь соединение и повтори позже.';
  });
})();
