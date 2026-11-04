/* Independent passwordless email login and Telegram widget on Render. */
(() => {
  'use strict';
  const root=document.getElementById('account-auth-panel');
  if(!root)return;
  const $=selector=>root.querySelector(selector);
  const tabs=[...root.querySelectorAll('[data-auth-tab]')];
  const panes=[...root.querySelectorAll('[data-auth-pane]')];
  const availability=$('[data-auth-availability]');
  const tgStatus=$('#account-auth-status');
  const retry=$('#account-telegram-retry');
  const emailForm=$('[data-auth-form="email"]');
  const verifyForm=$('[data-auth-verify="email"]');
  const emailField=$('#auth-email-input');
  const codeField=$('#auth-email-code');
  const emailMsg=$('[data-auth-message="email"]');
  let requestedEmail='';
  let ready=false;
  const errorMessages={
    EMAIL_LOGIN_COOLDOWN:'Повторный запрос возможен позже. Проверь почту.',
    EMAIL_LOGIN_LIMIT:'Слишком много запросов. Попробуй позже.',
    EMAIL_LOGIN_INVALID_CODE:'Неверный или просроченный код. Проверь письмо.',
    EMAIL_LOGIN_NOT_CONFIGURED:'Вход по почте пока не настроен на сервере.',
    EMAIL_DELIVERY_UNAVAILABLE:'Письмо не отправлено. Проверь настройку отправителя.',
    EMAIL_LOGIN_DATABASE_UNAVAILABLE:'Временная проблема с базой данных.',
    INVALID_ORIGIN:'Некорректный адрес сайта. Открой кабинет на Render.'
  };
  function say(message){if(emailMsg)emailMsg.textContent=message;}
  function select(method){
    for(const tab of tabs){
      const chosen=tab.dataset.authTab===method;
      tab.setAttribute('aria-selected',String(chosen));
      tab.tabIndex=chosen?0:-1;
    }
    for(const pane of panes)pane.hidden=pane.dataset.authPane!==method;
  }
  for(let i=0;i<tabs.length;i++){
    tabs[i].addEventListener('click',()=>select(tabs[i].dataset.authTab));
    tabs[i].addEventListener('keydown',event=>{
      if(event.key!=='ArrowLeft'&&event.key!=='ArrowRight')return;
      event.preventDefault();
      const n=(i+(event.key==='ArrowRight'?1:tabs.length-1))%tabs.length;
      tabs[n].focus();select(tabs[n].dataset.authTab);
    });
  }
  async function api(path,body){
    const response=await fetch(path,{
      method:'POST',credentials:'same-origin',cache:'no-store',
      headers:{'Content-Type':'application/json','Accept':'application/json'},
      body:JSON.stringify(body)
    });
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(data.detail||'Сервер недоступен');
    return data;
  }
  if(emailForm)emailForm.addEventListener('submit',async event=>{
    event.preventDefault();
    if(!ready||!emailField?.value)return;
    const button=emailForm.querySelector('button[type="submit"]');
    button.disabled=true;
    try{
      requestedEmail=emailField.value.trim();
      await api('/api/email-auth/request',{email:requestedEmail});
      verifyForm.hidden=false;
      codeField.hidden=false;
      codeField.focus();
      say('Код отправлен. Проверь входящие и спам. Он действует 10 минут.');
    }catch(error){
      say(errorMessages[error.message]||'Не удалось отправить код: '+error.message);
    }finally{button.disabled=false;}
  });
  if(verifyForm)verifyForm.addEventListener('submit',async event=>{
    event.preventDefault();
    if(!ready||!requestedEmail||!codeField?.value)return;
    const button=verifyForm.querySelector('button[type="submit"]');
    button.disabled=true;
    try{
      const result=await api('/api/email-auth/verify',{
        email:requestedEmail,code:codeField.value.trim()
      });
      if(!result.authenticated||!result.user)throw Error('INVALID_RESPONSE');
      codeField.value='';
      say('Адрес подтверждён. Вход выполнен.');
      if(typeof window.onVainahEmailAuth==='function'){
        window.onVainahEmailAuth(result.user);
      }else{
        window.location.assign('account.html');
      }
    }catch(error){
      say(errorMessages[error.message]||'Не удалось подтвердить код: '+error.message);
    }finally{button.disabled=false;}
  });
  async function initTelegram(){
    try{
      const response=await fetch('/api/telegram/config',{cache:'no-store'});
      if(!response.ok)throw Error('Telegram API недоступен');
      const cfg=await response.json();
      if(!cfg.available){
        if(tgStatus)tgStatus.textContent=cfg.message||'Telegram Login не настроен.';
        if(retry)retry.disabled=true;
        return;
      }
      if(!window.VainahTelegramWidget)throw Error('Виджет Telegram не загрузился');
      window.VainahTelegramWidget.mount({
        container:$('#account-widget'),status:tgStatus,retry,
        callback:'onVainahAccountAuth(user)',botUsername:cfg.bot_username
      });
    }catch(error){if(tgStatus)tgStatus.textContent=error.message;}
  }
  async function initEmail(){
    try{
      const response=await fetch('/api/email-auth/config',{cache:'no-store'});
      if(!response.ok)throw Error('Сервис входа по почте недоступен');
      const cfg=await response.json();
      ready=cfg.available===true;
      if(emailField)emailField.disabled=!ready;
      const button=emailForm?.querySelector('button[type="submit"]');
      if(button)button.disabled=!ready;
      const missing=Array.isArray(cfg.missing_settings)
        ?cfg.missing_settings.filter(item=>typeof item==='string').join(', ')
        :'';
      say(ready
        ?'Введи свою почту. Пришлём код для входа, пароль не нужен.'
        :(missing?'В Render проверь переменные: '+missing:
          'Вход по email пока не настроен.'));
      if(availability)availability.textContent=ready
        ?'Вход через email активен. Telegram тоже можно использовать отдельно.'
        :'Вход по email требует подтверждённого отправителя и PostgreSQL.';
    }catch(error){
      say(error.message);
      if(availability)availability.textContent='Не удалось проверить почтовую авторизацию.';
    }
  }
  if(tabs.length)select('email');
  void initEmail();
  void initTelegram();
})();
