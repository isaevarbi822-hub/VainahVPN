/* Verified Telegram and email dashboard. Never fabricate subscriptions. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const write=(id,value)=>{const node=$(id);if(node)node.textContent=value;};
  const hide=(id,value)=>{const node=$(id);if(node)node.hidden=value;};
  let user=null;
  let subscriptionUrl=null;
  let currentData=null;
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
  function resetPrivate(){
    currentData=null;subscriptionUrl=null;
    hide('account-open-vpn',true);
    hide('account-copy-vpn',true);
    const copy=$('account-copy-vpn');
    if(copy)copy.disabled=true;
    const get=$('account-get-vpn');
    if(get)get.disabled=true;
    write('metric-plan','Нет подтверждённых покупок');
    write('metric-expiry','—');
    write('metric-devices','—');
    write('account-plan-name','Подписка не оформлена');
    write('account-plan-sub','Реальные платежи пока отключены.');
    write('account-plan-price','—');
    write('account-plan-chip','Нет оплаченного заказа');
    write('account-access-status','Ключ будет доступен после подтверждения оплаты и выдачи персональной подписки.');
    write('account-device-limit','—');
    write('account-device-note','Лимит появится после покупки.');
    write('account-h1-state','Проверяем H1Cloud…');
    write('account-history-count','0');
    write('account-history-hint','В истории отображаются только подтверждённые покупки.');
    const history=$('account-order-list');
    if(history)history.textContent='Пока нет подтверждённых покупок.';
  }
  function showSession(next){
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
    const refreshButton=$('account-refresh');
    if(refreshButton)refreshButton.disabled=true;
    try{
      const result=await api('/api/account/overview');
      if(!user)return;
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
      const history=$('account-order-list');
      if(history){
        history.replaceChildren();
        for(const order of orders){
          const el=document.createElement('p');
          el.textContent=order.title+' · '+order.status;
          history.append(el);
        }
        if(!orders.length)history.textContent='Заказов пока нет.';
      }
      const delivery=result.subscription;
      const ready=delivery?.status==='delivered'&&delivery?.paid===true;
      if(ready){
        write('metric-plan',delivery.plan_title||'VPN-подписка');
        write('metric-expiry',delivery.expires_at||'—');
        write('metric-devices',String(delivery.device_limit||'—'));
        write('account-plan-name',delivery.plan_title||'Активный тариф');
        write('account-plan-chip','Оплачено · доступ выдан');
        write('account-access-status','Доступ доступен. Личную ссылку можно открыть или скопировать.');
        const get=$('account-get-vpn');if(get)get.disabled=false;
      }
    }catch(error){
      write('account-h1-state','Не удалось загрузить кабинет: '+error.message);
    }finally{if(refreshButton)refreshButton.disabled=false;}
  }
  const get=$('account-get-vpn');
  if(get)get.addEventListener('click',async()=>{
    if(!user||!currentData?.subscription?.order_id)return;
    get.disabled=true;
    try{
      const response=await api('/api/account/access');
      const url=new URL(response.subscription_url);
      if(url.protocol!=='https:'||url.username||url.password)throw Error('INVALID_LINK');
      subscriptionUrl=url.href;
      const open=$('account-open-vpn');
      if(open){open.href=subscriptionUrl;open.referrerPolicy='no-referrer';open.hidden=false;}
      hide('account-copy-vpn',false);
      const copy=$('account-copy-vpn');if(copy)copy.disabled=false;
      write('account-access-status','Ссылка готова. Никому не передавай свой ключ.');
    }catch(error){write('account-access-status','Не удалось получить ссылку: '+error.message);}
    finally{get.disabled=false;}
  });
  const copy=$('account-copy-vpn');
  if(copy)copy.addEventListener('click',async()=>{
    if(!subscriptionUrl)return;
    try{
      await navigator.clipboard.writeText(subscriptionUrl);
      write('account-access-status','Личная ссылка скопирована.');
    }catch{write('account-access-status','Не удалось скопировать ссылку.');}
  });
  const logout=$('account-exit');
  if(logout)logout.addEventListener('click',async()=>{
    try{
      await api('/api/email-auth/logout',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({})
      });
    }catch{write('account-auth-status','Не удалось выйти из аккаунта.');return;}
    showSession(null);
  });
  const refreshButton=$('account-refresh');
  if(refreshButton)refreshButton.addEventListener('click',refresh);
  const form=$('account-email-form');
  if(form)form.addEventListener('submit',async(event)=>{
    event.preventDefault();
    if(!user)return;
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
      hide('account-email-verify',false);
      write('account-email-status','Код отправлен на почту. Введи его для подтверждения.');
    }catch(error){write('account-email-status','Не удалось отправить код: '+error.message);}
    finally{button.disabled=false;}
  });
  const verifyForm=$('account-email-verify');
  if(verifyForm)verifyForm.addEventListener('submit',async(event)=>{
    event.preventDefault();
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
      write('account-email-status','Адрес подтверждён: '+email.email);
      hide('account-email-verify',true);
      await refresh();
    }catch(error){write('account-email-status','Не удалось подтвердить почту: '+error.message);}
    finally{button.disabled=false;}
  });
  async function resumeSession(){
    try{
      const tg=await api('/api/telegram/account');
      if(tg.authenticated&&tg.user){
        showSession({...tg.user,auth_method:'telegram'});
        return;
      }
    }catch{ /* Email is independent of Telegram availability. */ }
    try{
      const email=await api('/api/email-auth/account');
      if(email.authenticated&&email.user){
        showSession(email.user);
        return;
      }
    }catch{ /* No active email session. */ }
    showSession(null);
  }
  void resumeSession();
})();
