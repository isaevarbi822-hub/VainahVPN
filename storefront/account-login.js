/* Telegram Login Widget backed by signature verification on the Render API. */
(() => {
  'use strict';
  const root=document.getElementById('account-auth-panel');
  if(!root)return;
  const $=(selector)=>root.querySelector(selector);
  const tabs=[...root.querySelectorAll('[data-auth-tab]')];
  const panes=[...root.querySelectorAll('[data-auth-pane]')];
  const availability=$('[data-auth-availability]');
  const tgStatus=$('#account-auth-status');
  const retry=$('#account-telegram-retry');
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
  const emailForm=$('[data-auth-form="email"]');
  if(emailForm){
    emailForm.addEventListener('submit',event=>event.preventDefault());
    for(const field of emailForm.querySelectorAll('input,button'))field.disabled=true;
  }
  const verifyForm=$('[data-auth-verify="email"]');
  if(verifyForm)verifyForm.addEventListener('submit',event=>event.preventDefault());
  const msg=$('[data-auth-message="email"]');
  if(msg)msg.textContent='Вход только по email ещё не подключён. Привязать email можно после входа через Telegram.';
  async function init(){
    try{
      const response=await fetch('/api/telegram/config',{cache:'no-store'});
      if(!response.ok)throw Error('Сервис авторизации недоступен.');
      const config=await response.json();
      if(!config.available){
        if(tgStatus)tgStatus.textContent=config.message||'Telegram Login не настроен на сервере.';
        if(availability)availability.textContent='Настрой Telegram-бота в Render и разреши домен в BotFather.';
        if(retry)retry.disabled=true;
        return;
      }
      if(availability)availability.textContent='Telegram Login доступен. Почту можно подтвердить в личном кабинете.';
      if(!window.VainahTelegramWidget)throw Error('Не загрузился официальный модуль Telegram.');
      window.VainahTelegramWidget.mount({
        container:$('#account-widget'),status:tgStatus,retry,
        callback:'onVainahAccountAuth(user)',botUsername:config.bot_username
      });
    }catch(error){
      if(tgStatus)tgStatus.textContent=error.message;
    }
  }
  if(tabs.length)select('telegram');
  void init();
})();
