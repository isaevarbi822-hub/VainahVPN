/* Funded Vainah gift cards; safe while sales are independently disabled. */
(() => {
  'use strict';
  const root=document.getElementById('gift-paid-content');
  const status=document.getElementById('gift-paid-status');
  if(!root||!status)return;
  const node=(tag,value='',cls='')=>{
    const element=document.createElement(tag);
    element.textContent=String(value);
    if(cls)element.className=cls;
    return element;
  };
  const api=async(path,options={})=>{
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),30000);
    let response,data;
    try{
      response=await fetch(path,{
        method:'GET',cache:'no-store',credentials:'same-origin',
        ...options,headers:{Accept:'application/json',...(options.headers||{})},
        signal:controller.signal,
      });
      if(response.ok)data=await response.json();
    }catch{
      if(controller.signal.aborted)throw Error('Сервер не ответил вовремя. Проверь статус и повтори попытку.');
      throw Error('Сервис подарков не ответил. Проверь соединение и повтори попытку.');
    }finally{clearTimeout(timer);}
    if(!response.ok){
      const error=new Error(response.status===401?
        'Войди через подтверждённую почту в личном кабинете.':
        response.status===404?
          (path.endsWith('/redeem')?'Код не найден, уже использован или недоступен.':
            'Раздел временно недоступен (HTTP 404). Обратись в поддержку.'):
        response.status===409?'Подарок требует проверки поддержки. Не оплачивай повторно.':
        response.status===422?'Проверь код или выбранный тариф.':
        response.status===503?'Сервис подарков временно недоступен. Не оплачивай повторно.':
        'Не удалось выполнить действие. Ошибка '+response.status+'.');
      error.status=response.status;
      throw error;
    }
    if(!data||typeof data!=='object'||Array.isArray(data))throw Error('Некорректный ответ сервиса подарков.');
    return data;
  };
  const say=text=>{status.textContent=text;};
  const action=(text,callback,secondary=false)=>{
    const button=node('button',text,secondary?'secondary':'');
    button.type='button';
    button.addEventListener('click',async()=>{
      button.disabled=true;
      try{await callback();}catch(error){say(error.message);}
      finally{button.disabled=false;}
    });
    return button;
  };
  const item=(title,description)=>{
    const section=node('article','','notice');
    section.append(node('strong',title),node('p',description));
    return section;
  };
  const checkoutNonces=new Map();
  let listRevision=0;
  function paidPageReady(info){
    root.replaceChildren();
    root.append(node('h2','Купить настоящую подарочную подписку'));
    const explanation=node('p',
      info.purchase_enabled?
        'После подтверждённой оплаты RollyPay здесь появится подарочный код. До его активации VPN не выдаётся.':
        'Отдельная оплата подарочных карт пока не включена. Не оплачивай обычную подписку вместо подарка.',
      info.purchase_enabled?'note':'warning');
    root.append(explanation);
    const plan=node('select');
    plan.setAttribute('aria-label','Тариф подарочной карты');
    const planIds=new Set(['30','60','90','180','365','365-family']);
    const catalog=Array.isArray(info.plans)?info.plans:[];
    for(const offer of catalog){
      if(!offer||!planIds.has(offer.id)||typeof offer.price_rub!=='string'||
         !/^\d{1,6}\.\d{2}$/.test(offer.price_rub)||typeof offer.title!=='string'||!offer.title.trim())continue;
      const option=node('option',offer.title+' · '+offer.price_rub+' ₽');
      option.value=offer.id;plan.append(option);
    }
    const planBox=node('div','','row');
    const checkout=action('Перейти к безопасной оплате RollyPay',async()=>{
      if(!window.crypto||typeof window.crypto.randomUUID!=='function'){
        throw Error('Браузер не поддерживает безопасное создание номера заказа.');
      }
      const planId=plan.value;
      if(!planId)throw Error('Выбери тариф подарочной карты.');
      if(!checkoutNonces.has(planId))checkoutNonces.set(planId,window.crypto.randomUUID());
      const result=await api('/api/account/gift-cards/checkout',{
        method:'POST',headers:{'Content-Type':'application/json',
          'Idempotency-Key':checkoutNonces.get(planId)},
        body:JSON.stringify({plan_id:planId}),
      });
      const link=new URL(String(result.pay_url||''));
      if(link.protocol!=='https:'||link.host!=='pay.rollypay.io'||
         !/^\/pay\/[A-Za-z0-9_-]+\/?$/.test(link.pathname)||
         link.search||link.hash||link.username||link.password){
        throw Error('Провайдер вернул непроверенную ссылку оплаты.');
      }
      window.location.assign(link.href);
    });
    checkout.disabled=info.purchase_enabled!==true||plan.options.length===0;
    if(info.purchase_enabled===true&&!plan.options.length){
      explanation.textContent='Цены подарочных тарифов не загрузились. Обнови страницу.';
    }
    planBox.append(plan,checkout);root.append(planBox);
    root.append(node('h2','Активировать подарочный код'));
    root.append(node('p','Код действителен только после подтверждения оплаты. Войди в аккаунт получателя.','note'));
    const code=node('input');
    code.placeholder='VG...';code.maxLength=34;
    code.setAttribute('aria-label','Подарочный код из 34 символов');
    code.autocomplete='off';code.spellcheck=false;
    const redeem=action('Активировать код',async()=>{
      const giftCode=code.value.trim().toUpperCase();
      if(!/^VG[A-F0-9]{32}$/.test(giftCode)){
        throw Error('Неверный формат подарочного кода.');
      }
      const result=await api('/api/account/gift-cards/redeem',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({code:giftCode}),
      });
      if(result.vpn_delivered!==true)throw Error('Подарок не подтверждён. Проверь обращения.');
      code.value='';
      say('Подписка активирована. VPN доступен в кабинете получателя.'+
          (result.email_pending?' Письмо отправится после повторной проверки.':''));
      await refreshLists();
    });
    redeem.disabled=info.redemption_available!==true;
    if(info.redemption_available!==true){
      root.append(node('p',
        'Активация ранее оплаченных кодов сейчас недоступна. Не покупай второй подарок: обратитесь в поддержку с номером заказа, без отправки кода в публичный чат.',
        'warning'));
    }
    const redeemBox=node('div','','row');
    redeemBox.append(code,redeem);root.append(redeemBox);
    const buyerSection=node('div');buyerSection.id='gift-buyer-list';root.append(buyerSection);
    const recipientSection=node('div');recipientSection.id='gift-recipient-list';
    root.append(recipientSection);
    root.append(action('Обновить статусы подарков',async()=>{
      const loaded=await refreshLists();
      if(loaded===true)say('Статусы купленных и полученных подарков обновлены.');
      if(loaded===false)say('Часть статусов не загрузилась. Подробности указаны рядом со списками.');
    },true));
  }
  async function refreshLists(){
    const buyer=document.getElementById('gift-buyer-list');
    const recipient=document.getElementById('gift-recipient-list');
    if(!buyer||!recipient)return;
    const revision=++listRevision;
    buyer.replaceChildren(node('h2','Мои купленные подарки'));
    recipient.replaceChildren(node('h2','Полученные подарки'));
    try{
      const [purchaseResult,receivedResult]=await Promise.allSettled([
        api('/api/account/gift-cards/mine'),
        api('/api/account/gift-cards/received'),
      ]);
      if(revision!==listRevision)return;
      const purchases=purchaseResult.status==='fulfilled'?purchaseResult.value:null;
      const received=receivedResult.status==='fulfilled'?receivedResult.value:null;
      const cards=Array.isArray(purchases?.items)?purchases.items:[];
      if(!Array.isArray(purchases?.items)){
        buyer.append(node('p',purchaseResult.reason?.message||
          'Не удалось получить список купленных подарков.','warning'));
      }else if(!cards.length){
        buyer.append(node('p','Оплаченных подарков пока нет.','note'));
      }
      for(const record of cards){
        if(!record||typeof record!=='object')continue;
        const card=item('Тариф '+String(record.plan_id||''),
          'Платёж: '+String(record.payment_state||'неизвестно')+
          '. Выдача: '+String(record.delivery_state||'неизвестно')+'.');
        if(record.redeemed===true){
          card.append(node('p','Код уже использован.','note'));
        }else if(typeof record.gift_code==='string'&&/^VG[A-F0-9]{32}$/.test(record.gift_code)){
          card.append(node('p','Подарочный код: '+record.gift_code,'note'));
          card.append(action('Скопировать подарочный код',async()=>{
            await navigator.clipboard.writeText(record.gift_code);
            say('Код скопирован. Передай его только получателю.');
          },true));
        }else{
          card.append(node('p','Код появится только после подписанного платежа.','note'));
        }
        buyer.append(card);
      }
      const receivedItems=Array.isArray(received?.items)?received.items:[];
      if(!Array.isArray(received?.items)){
        recipient.append(node('p',receivedResult.reason?.message||
          'Не удалось загрузить полученные подарки.','warning'));
      }else if(!receivedItems.length){
        recipient.append(node('p','Полученных подарков ещё нет.','note'));
      }
      for(const record of receivedItems){
        if(!record||typeof record!=='object')continue;
        const card=item('Полученный тариф '+String(record.plan_id||''),
          'Выдача: '+String(record.delivery_state||'проверяется')+'.');
        if(record.can_finish===true&&typeof record.order_id==='string'&&
           /^vainah_live_[0-9a-f]{32}$/.test(record.order_id)){
          card.append(action('Завершить выдачу после прерывания',async()=>{
            const outcome=await api('/api/account/gift-cards/'+
              encodeURIComponent(record.order_id)+'/finish',{method:'POST'});
            say(outcome.vpn_delivered===true?
              'Выдача завершена. Подписка доступна в кабинете.':
              'Выдача требует проверки поддержки.');
            await refreshLists();
          },true));
        }else if(record.delivery_state==='manual_review'){
          card.append(node('p','Обратись в поддержку: повторно выдавать VPN небезопасно.','warning'));
        }
        recipient.append(card);
      }
      return Array.isArray(purchases?.items)&&Array.isArray(received?.items);
    }catch(error){
      buyer.append(node('p',error.message,'note'));
      recipient.append(node('p','Список недоступен. Обнови страницу после входа.','note'));
      return false;
    }
  }
  async function initialize(){
    say('Проверяем настройки подарочных карт…');
    try{
      const info=await api('/api/account/gift-cards/status');
      paidPageReady(info);
      say(info.purchase_enabled===true?
        'Покупка подарков доступна. Проверь цену и тариф перед переходом на RollyPay.':
        info.redemption_available===true?
          'Новые покупки пока закрыты; ранее оплаченные коды можно активировать.':
          'Новые покупки и активация сейчас недоступны. Черновики не являются подарками.');
      await refreshLists();
    }catch(error){
      say('Не удалось проверить подарочные карты: '+error.message);
      root.replaceChildren(node('p',
        'Не создавай второй платёж при ошибке страницы. Попробуй ещё раз или напиши в поддержку.',
        'warning'));
      const retry=action('Повторить проверку',initialize,true);
      const help=node('a','Поддержка Vainah VPN');
      help.href='/support-center.html';
      root.append(retry,help);
    }
  }
  void initialize();
})();
