/* A short-lived QR is separate from the permanent subscription QR. */
(() => {
  'use strict';
  const button=document.getElementById('account-handoff-create');
  const panel=document.getElementById('account-handoff-panel');
  const image=document.getElementById('account-handoff-image');
  const message=document.getElementById('account-handoff-status');
  if(!button||!panel||!image||!message)return;
  let objectUrl=null;
  let revision=0;
  function clear(){
    revision++;
    if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl=null;}
    image.removeAttribute('src');image.hidden=true;
    panel.hidden=true;
    button.disabled=false;
    button.textContent='Создать одноразовый QR · 5 минут';
    message.textContent='Новый QR не создан.';
  }
  button.addEventListener('click',async()=>{
    if(objectUrl){
      clear();return;
    }
    button.disabled=true;
    const requestRevision=++revision;
    message.textContent='Проверяем оплату и создаём код…';
    panel.hidden=false;
    try{
      const response=await fetch('/api/account/handoff/qr',{
        method:'POST',credentials:'same-origin',cache:'no-store',
        headers:{Accept:'image/svg+xml'}
      });
      if(!response.ok){
        if(response.status===401)throw Error('Сначала войди в подтверждённый аккаунт.');
        if(response.status===404)throw Error('Для одноразового QR требуется оплаченная и выданная подписка.');
        if(response.status===429)throw Error('Не более 3 кодов за 15 минут.');
        throw Error('Не удалось создать QR. Проверь подписку и повтори.');
      }
      if(!(response.headers.get('content-type')||'').includes('image/svg+xml'))
        throw Error('Неверный формат ответа сервера.');
      const blob=await response.blob();
      if(blob.size>500000 || blob.size===0)throw Error('Некорректный размер QR.');
      if(requestRevision!==revision)return;
      objectUrl=URL.createObjectURL(blob);
      image.src=objectUrl;image.hidden=false;
      message.textContent='Сканируй QR на втором устройстве в течение 5 минут. Войди в тот же аккаунт. Код одноразовый.';
      button.textContent='Скрыть одноразовый QR';
    }catch(error){
      if(requestRevision!==revision)return;
      message.textContent=error.message;
    }finally{
      if(requestRevision===revision)button.disabled=false;
    }
  });
  window.addEventListener('vainah-account-session',clear);
  window.addEventListener('pagehide',clear);
})();
