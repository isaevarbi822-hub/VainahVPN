/* Official Telegram Login Widget. The backend verifies each auth callback. */
(() => {
  'use strict';
  function mount({container,status,retry,callback,botUsername}={}){
    if(!container||!status||!retry||!callback)return;
    if(!/^[A-Za-z][A-Za-z0-9_]{4,31}$/.test(botUsername||'')){
      status.textContent='Имя Telegram-бота не настроено.';
      return;
    }
    let sequence=0,timer;
    function load(){
      const current=++sequence;
      if(timer)clearTimeout(timer);
      container.replaceChildren();
      retry.disabled=true;
      retry.textContent='Загрузка…';
      status.textContent='Загружаем официальную кнопку Telegram…';
      const script=document.createElement('script');
      script.async=true;
      script.src='https://telegram.org/js/telegram-widget.js?22';
      script.setAttribute('data-telegram-login',botUsername);
      script.setAttribute('data-size','large');
      script.setAttribute('data-radius','12');
      script.setAttribute('data-onauth',callback);
      script.onerror=()=>{
        if(current!==sequence)return;
        if(timer)clearTimeout(timer);
        retry.disabled=false;retry.textContent='↻ Повторить';
        status.textContent='Telegram не загрузился: проверь блокировщики и сеть.';
      };
      script.onload=()=>{
        if(current!==sequence)return;
        retry.disabled=false;retry.textContent='↻ Перезагрузить';
      };
      container.append(script);
      timer=setTimeout(()=>{
        if(current!==sequence)return;
        retry.disabled=false;retry.textContent='↻ Повторить';
        status.textContent=container.querySelector('iframe')
          ?'Нажми «Log in with Telegram» и подтверди вход.'
          :'Кнопка не появилась. Проверь домен в BotFather и блокировщики браузера.';
      },9000);
    }
    retry.addEventListener('click',load);
    load();
  }
  window.VainahTelegramWidget={mount};
})();
