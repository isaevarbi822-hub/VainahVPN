/* Four real login methods. No passwords, fake sessions or cross-provider order access. */
(function(){
  'use strict';
  const root=document.getElementById('account-auth-panel');
  if(!root)return;
  const $=selector=>root.querySelector(selector);
  const tabs=[...root.querySelectorAll('[data-auth-tab]')];
  const panes=[...root.querySelectorAll('[data-auth-pane]')];
  const info=$('[data-auth-availability]');
  const tgStatus=$('#account-auth-status');
  const tgRetry=$('#account-telegram-retry');
  const methods={email:false,phone:false,yandex:false,telegram:false};
  let selected='telegram',challenge=null,sending=false;
  function message(el,text){if(el)el.textContent=text}
  function select(method){
    selected=method;
    for(const tab of tabs){
      const active=tab.dataset.authTab===method;
      tab.setAttribute('aria-selected',String(active));
      tab.tabIndex=active?0:-1;
    }
    for(const pane of panes)pane.hidden=pane.dataset.authPane!==method;
    if(method!=='telegram'&&!methods[method])
      message($('[data-auth-message="'+method+'"]'),
        'Этот способ входа пока не подключён в Netlify. Понадобится настройка провайдера подтверждения.');
  }
  for(let i=0;i<tabs.length;i++){
    tabs[i].addEventListener('click',()=>select(tabs[i].dataset.authTab));
    tabs[i].addEventListener('keydown',event=>{
      if(event.key!=='ArrowLeft'&&event.key!=='ArrowRight')return;
      event.preventDefault();
      const next=(i+(event.key==='ArrowRight'?1:tabs.length-1))%tabs.length;
      tabs[next].focus();select(tabs[next].dataset.authTab);
    });
  }
  async function api(path,body){
    const response=await fetch('/.netlify/functions/'+path,{
      method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',
      headers:body?{'Content-Type':'application/json',Accept:'application/json'}:{Accept:'application/json'},
      body:body?JSON.stringify(body):undefined
    });
    const result=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(result.error||'Сервер недоступен ('+response.status+')');
    return result;
  }
  async function availability(){
    try{
      const result=await api('alternate-login');
      Object.assign(methods,result.available||{});
      info.textContent='Способы входа: Telegram'+
        (methods.email?', почта':'')+(methods.phone?', телефон':'')+
        (methods.yandex?', Яндекс':'')+'.';
      for(const method of ['email','phone']){
        const form=$('[data-auth-form="'+method+'"]');
        const submit=form?.querySelector('[type="submit"]');
        if(submit)submit.disabled=!methods[method];
      }
      const link=$('#account-yandex-start');
      link.hidden=!methods.yandex;
      const warning=$('#account-yandex-disabled');
      warning.hidden=methods.yandex;
      if(!methods.telegram)
        message(tgStatus,'Для Telegram Login проверь TELEGRAM_BOT_TOKEN, SESSION_SIGNING_KEY, PUBLIC_SITE_ORIGIN и домен, разрешённый в BotFather.');
    }catch{
      info.textContent='Не получилось проверить способы входа. Попробуй обновить страницу.';
    }
  }
  for(const method of ['email','phone']){
    const form=$('[data-auth-form="'+method+'"]');
    const contact=$('[data-auth-contact="'+method+'"]');
    const code=$('[data-auth-code="'+method+'"]');
    const verify=$('[data-auth-verify="'+method+'"]');
    const status=$('[data-auth-message="'+method+'"]');
    form.addEventListener('submit',async event=>{
      event.preventDefault();
      if(sending||!methods[method])return;
      sending=true;const button=form.querySelector('[type="submit"]');
      button.disabled=true;
      message(status,'Отправляем настоящий код подтверждения…');
      try{
        const normalized=contact.value.trim();
        await api('alternate-login',{action:'send',method,contact:normalized});
        challenge={method,contact:normalized};
        code.hidden=false;verify.hidden=false;
        code.focus();
        message(status,'Код отправлен. Введи цифры из сообщения. Код действителен примерно 10 минут.');
      }catch(error){
        message(status,error.message);
      }finally{
        sending=false;button.disabled=!methods[method];
      }
    });
    verify.addEventListener('submit',async event=>{
      event.preventDefault();
      if(sending||challenge?.method!==method||
        challenge.contact!==contact.value.trim())return;
      const button=verify.querySelector('[type="submit"]');
      sending=true;button.disabled=true;
      message(status,'Проверяем код…');
      try{
        const result=await api('alternate-login',{
          action:'check',method,contact:challenge.contact,code:code.value.trim()
        });
        if(!result.authenticated)throw Error('Не удалось подтвердить вход');
        code.value='';
        message(status,'Подтверждено. Открываем отдельный аккаунт…');
        if(typeof window.onVainahAltLogin==='function')
          window.onVainahAltLogin({provider:method});
        else window.location.assign('account.html');
      }catch(error){
        message(status,error.message);
      }finally{sending=false;button.disabled=false}
    });
    contact.addEventListener('input',()=>{
      if(challenge?.method===method&&challenge.contact!==contact.value.trim()){
        code.hidden=true;verify.hidden=true;challenge=null;
      }
    });
  }
  if(window.VainahTelegramWidget){
    window.VainahTelegramWidget.mount({
      container:$('#account-widget'),status:tgStatus,retry:tgRetry,
      callback:'onVainahAccountAuth(user)'
    });
  }else{
    message(tgStatus,'Не удалось загрузить модуль Telegram Login. Обнови страницу.');
  }
  const hint=new URLSearchParams(window.location.search).get('alt_login');
  if(hint==='error')info.textContent='Яндекс не подтвердил вход. Попробуй ещё раз или выбери другой способ.';
  if(hint==='success')info.textContent='Яндекс подтвердил вход. Проверяем защищённую сессию…';
  select('telegram');
  void availability();
})();
