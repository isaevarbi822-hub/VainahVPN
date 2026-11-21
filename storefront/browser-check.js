/* Checks only browser capabilities, with no fingerprinting or network calls. */
(() => {
  'use strict';
  const root=document.getElementById('browser-tools');
  if(!root)return;
  const button=document.getElementById('browser-run');
  const summary=document.getElementById('browser-summary');
  const targets={
    secure:document.getElementById('browser-secure'),
    clipboard:document.getElementById('browser-clipboard'),
    network:document.getElementById('browser-network'),
    dialogs:document.getElementById('browser-dialogs'),
    responsive:document.getElementById('browser-responsive')
  };
  function fill(name,good,description){
    const item=targets[name];
    if(!item)return;
    const status=item.querySelector('[data-browser-status]');
    const detail=item.querySelector('[data-browser-detail]');
    status.textContent=good?'Доступно':'Ограничено';
    status.dataset.state=good?'good':'warn';
    detail.textContent=description;
  }
  button.addEventListener('click',()=>{
    const secure=window.isSecureContext===true;
    const clipboard=Boolean(navigator.clipboard?.writeText);
    const online=navigator.onLine!==false;
    const dialogs=typeof HTMLDialogElement!=='undefined'&&
      typeof HTMLDialogElement.prototype.showModal==='function';
    const responsive=Boolean(window.matchMedia?.('(max-width: 700px)'));
    fill('secure',secure,secure?
      'Страница использует безопасный контекст.':'Открой сайт по HTTPS для защищённых возможностей.');
    fill('clipboard',clipboard,clipboard?
      'Копирование может работать после нажатия кнопки. Разрешение зависит от браузера.':
      'Автоматическое копирование не поддерживается. Можно выделить и скопировать текст вручную.');
    fill('network',online,online?
      'Браузер сообщает, что сеть доступна; это не проверка VPN-туннеля.':
      'Браузер сообщает, что сеть недоступна. Проверь Wi-Fi или мобильную сеть.');
    fill('dialogs',dialogs,dialogs?
      'Встроенные диалоги поиска поддерживаются.':
      'Доступность модального поиска может отличаться. Используй каталог функций.');
    fill('responsive',responsive, responsive?
      'Определены возможности адаптивной вёрстки.':
      'Не удалось определить адаптивные возможности браузера.');
    summary.textContent='Проверка завершена. Результаты относятся только к функциям веб-сайта, а не к работе VPN-клиента.';
    button.textContent='Повторить проверку';
  });
})();
