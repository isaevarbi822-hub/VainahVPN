/* Reliable legacy Telegram Login Widget. The callback is verified on the server. */
(function(){
  'use strict';
  function mount(options){
    const {container,status,retry,callback}=options||{};
    if(!container||!status||!retry||!callback)return;
    let sequence=0,timer=null;
    function display(message){status.textContent=message}
    function load(){
      sequence++;const current=sequence;
      if(timer)clearTimeout(timer);
      container.replaceChildren();
      retry.disabled=true;retry.textContent='Загрузка…';
      display('Загружаем официальную кнопку Telegram…');
      const script=document.createElement('script');
      script.async=true;
      script.src='https://telegram.org/js/telegram-widget.js?22';
      script.setAttribute('data-telegram-login','VainahVPNbot');
      script.setAttribute('data-size','large');
      script.setAttribute('data-radius','12');
      script.setAttribute('data-onauth',callback);
      script.onerror=()=>{
        if(current!==sequence)return;
        retry.disabled=false;retry.textContent='↻ Повторить загрузку';
        display('Кнопка не загрузилась. Проверь доступность telegram.org или настройки браузера.');
      };
      script.onload=()=>{
        if(current!==sequence)return;
        retry.disabled=false;retry.textContent='↻ Перезагрузить кнопку';
      };
      container.append(script);
      timer=setTimeout(()=>{
        if(current!==sequence)return;
        retry.disabled=false;retry.textContent='↻ Повторить загрузку';
        if(container.querySelector('iframe'))
          display('Нажми кнопку Telegram выше, чтобы подтвердить вход.');
        else
          display('Кнопка не появилась. Проверь домен в BotFather и загрузку официального виджета Telegram. При необходимости нажми «Повторить».');
      },10000);
    }
    retry.addEventListener('click',load);
    load();
  }
  window.VainahTelegramWidget={mount};
})();
