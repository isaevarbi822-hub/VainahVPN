/* One-use QR handoff. Token stays in memory and is erased from URL immediately. */
(() => {
  'use strict';
  const status=document.getElementById('handoff-status');
  const redeem=document.getElementById('handoff-redeem');
  const copy=document.getElementById('handoff-copy');
  if(!status||!redeem||!copy)return;
  const fragment=new URLSearchParams(location.hash.replace(/^#/, ''));
  const candidate=fragment.get('t');
  const token=typeof candidate==='string'&&/^[A-Za-z0-9_-]{32}$/.test(candidate)
    ?candidate:null;
  history.replaceState(null,'',location.pathname);
  let privateUrl=null;
  if(!token){
    status.textContent='QR-код недействителен или не передал токен. Открой новый QR в кабинете.';
    return;
  }
  status.textContent='Код распознан. Войди в тот же аккаунт и нажми кнопку.';
  redeem.disabled=false;
  redeem.addEventListener('click',async()=>{
    redeem.disabled=true;
    status.textContent='Проверяем аккаунт, оплату и срок действия кода…';
    try{
      const response=await fetch('/api/account/handoff/redeem',{
        method:'POST',credentials:'same-origin',cache:'no-store',
        headers:{Accept:'application/json','Content-Type':'application/json'},
        body:JSON.stringify({token})
      });
      if(!response.ok){
        if(response.status===401)throw Error('Войди в тот же аккаунт, затем отсканируй QR заново.');
        if(response.status===404)throw Error('Код истёк, использован или принадлежит другому аккаунту.');
        throw Error('Проверка не пройдена. Подписка и код не были выданы.');
      }
      const result=await response.json();
      if(result.redeemed!==true || typeof result.subscription_url!=='string' ||
        !result.subscription_url.startsWith('https://')){
        throw Error('Сервер вернул неожиданный ответ.');
      }
      privateUrl=result.subscription_url;
      copy.hidden=false;copy.disabled=false;
      status.textContent='Подписка подтверждена. Скопируй ссылку и импортируй её в свой VPN-клиент.';
    }catch(error){
      status.textContent=error.message;
      redeem.disabled=false;
    }
  });
  copy.addEventListener('click',async()=>{
    if(!privateUrl)return;
    try{
      await navigator.clipboard.writeText(privateUrl);
      status.textContent='Личная ссылка скопирована. Никому её не передавай.';
    }catch{
      status.textContent='Браузер запретил копирование. Открой кабинет и используй обычный импорт.';
    }
  });
})();
