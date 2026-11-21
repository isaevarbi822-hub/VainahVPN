/* Reminder preference: explicit opt-in, no automatic mail is sent. */
(() => {
  'use strict';
  const box=document.getElementById('account-reminder-optin');
  const status=document.getElementById('account-reminder-status');
  if(!box||!status)return;
  let revision=0;
  const deliveryText=(result)=>result.delivery_active===true
    ?'Email-напоминания настроены на стороне сервиса. Письма отправляются только при твоём согласии и подтверждённой подписке.'
    :'Выбор сохранён. Автоматические email-письма ещё не запущены. Напоминания на сайте доступны в разделе уведомлений.';
  async function api(method,body){
    const response=await fetch('/api/account/reminder-preference',{
      method,credentials:'same-origin',cache:'no-store',
      headers:{Accept:'application/json',...(body?{'Content-Type':'application/json'}:{})},
      ...(body?{body:JSON.stringify(body)}:{})
    });
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Ошибка сервера');
    return data;
  }
  async function reload(){
    const current=++revision;
    box.disabled=true;
    box.checked=false;
    status.textContent='Проверяем настройки…';
    try{
      const result=await api('GET');
      if(current!==revision)return;
      box.checked=result.enabled===true;
      box.disabled=false;
      status.textContent=deliveryText(result);
    }catch(error){
      if(current!==revision)return;
      box.disabled=true;
      status.textContent=error.message==='VERIFIED_EMAIL_REQUIRED'
        ?'Войди в аккаунт с подтверждённой почтой, чтобы настроить уведомления.'
        :'Не удалось загрузить настройки. Обнови кабинет и повтори попытку.';
    }
  }
  box.addEventListener('change',async()=>{
    const enabled=box.checked;
    const current=++revision;
    box.disabled=true;
    status.textContent='Сохраняем настройку…';
    try{
      const result=await api('POST',{enabled});
      if(current!==revision)return;
      box.checked=result.enabled===true;
      status.textContent=deliveryText(result);
    }catch{
      if(current!==revision)return;
      box.checked=!enabled;
      status.textContent='Не удалось сохранить выбор. Попробуй ещё раз.';
    }finally{
      if(current===revision)box.disabled=false;
    }
  });
  window.addEventListener('vainah-account-session',()=>void reload());
  void reload();
})();
