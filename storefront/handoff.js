/* One-use QR handoff. Token stays in memory and is erased from URL immediately. */
(() => {
  'use strict';
  const status=document.getElementById('handoff-status');
  const redeem=document.getElementById('handoff-redeem');
  const copy=document.getElementById('handoff-copy');
  if(!status||!redeem||!copy)return;
  const fragment=new URLSearchParams(location.hash.replace(/^#/, ''));
  const candidate=fragment.get('t');
  let token=typeof candidate==='string'&&/^[A-Za-z0-9_-]{32}$/.test(candidate)
    ?candidate:null;
  history.replaceState(null,'',location.pathname);
  let privateUrl=null;
  let pending=null;
  if(!token){
    status.textContent='QR-код недействителен или не передал токен. Открой новый QR в кабинете.';
    return;
  }
  status.textContent='Код распознан. Войди в тот же аккаунт и нажми кнопку.';
  redeem.disabled=false;
  redeem.addEventListener('click',async()=>{
    if(!token||pending)return;
    const controller=new AbortController();
    pending=controller;
    const timeout=setTimeout(()=>controller.abort(),20000);
    redeem.disabled=true;
    status.textContent='Проверяем аккаунт, оплату и срок действия кода…';
    try{
      const response=await fetch('/api/account/handoff/redeem',{
        method:'POST',credentials:'same-origin',cache:'no-store',
        headers:{Accept:'application/json','Content-Type':'application/json'},
        body:JSON.stringify({token}),signal:controller.signal
      });
      if(pending!==controller)return;
      if(!response.ok){
        if(response.status===401)throw Error('Войди в тот же аккаунт, затем отсканируй QR заново.');
        if(response.status===404){
          token=null;
          throw Error('Код истёк, использован или принадлежит другому аккаунту. Отсканируй новый QR.');
        }
        throw Error('Проверка не пройдена. Подписка и код не были выданы.');
      }
      const result=await response.json();
      if(pending!==controller)return;
      if(result.redeemed!==true || typeof result.subscription_url!=='string' ||
        !result.subscription_url.startsWith('https://')){
        throw Error('Сервер вернул неожиданный ответ.');
      }
      privateUrl=result.subscription_url;
      token=null;
      copy.hidden=false;copy.disabled=false;
      status.textContent='Подписка подтверждена. Скопируй ссылку и импортируй её в свой VPN-клиент.';
    }catch(error){
      if(pending!==controller)return;
      status.textContent=controller.signal.aborted
        ?'Сервер не ответил вовремя. Проверь ссылку в кабинете или отсканируй новый QR.'
        :error.message;
    }finally{
      clearTimeout(timeout);
      if(pending===controller){pending=null;redeem.disabled=!token;}
    }
  });
  copy.addEventListener('click',async()=>{
    if(!privateUrl)return;
    const link=privateUrl;
    try{
      await navigator.clipboard.writeText(link);
      if(link!==privateUrl)return;
      status.textContent='Личная ссылка скопирована. Никому её не передавай.';
    }catch{
      if(link===privateUrl)status.textContent='Браузер запретил копирование. Открой кабинет и используй обычный импорт.';
    }
  });
  window.addEventListener('pagehide',()=>{
    pending?.abort();pending=null;
    privateUrl=null;token=null;
    copy.hidden=true;copy.disabled=true;redeem.disabled=true;
    status.textContent='Чтобы продолжить перенос, отсканируй новый QR в кабинете.';
  });
})();
