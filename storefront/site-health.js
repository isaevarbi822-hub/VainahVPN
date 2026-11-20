/* Vainah status panel: explicit read-only check, no invoices, cookies or polling. */
(() => {
  'use strict';
  const privatePages=new Set([
    'checkout.html','checkout-return.html','payment-return.html','account.html',
    'account-login.html','support-operator.html','operator-pilot.html',
    'operations.html','my-devices.html','trial.html'
  ]);
  const path=location.pathname.split('/').pop()||'index.html';
  if(privatePages.has(path))return;
  const nav=document.querySelector('body > header .nav-side,body > header .header-actions');
  if(!nav||nav.querySelector('[data-vx-live-status]'))return;
  const button=document.createElement('button');
  button.type='button';
  button.className='vx-live-trigger';
  button.dataset.vxLiveStatus='true';
  button.setAttribute('aria-haspopup','dialog');
  button.setAttribute('aria-controls','vx-live-dialog');
  button.setAttribute('aria-label','Проверить доступность касс Vainah VPN');
  button.title='Проверка готовности RollyPay и Platega';
  button.innerHTML='<span class="vx-live-dot" aria-hidden="true"></span><span class="vx-live-label">Проверка оплаты</span>';
  nav.prepend(button);
  // On tiny phones the status shortcut lives inside the open menu, where
  // it remains reachable without squeezing the entire header off-screen.
  const mobileMenu=document.querySelector('body > header .mobile-nav');
  if(mobileMenu && !mobileMenu.querySelector('.vx-mobile-status')){
    const mobileStatus=document.createElement('button');
    mobileStatus.type='button';
    mobileStatus.className='vx-mobile-status';
    mobileStatus.textContent='◈ Проверка оплаты';
    mobileStatus.setAttribute('aria-label','Открыть проверку готовности RollyPay и Platega');
    mobileMenu.prepend(mobileStatus);
    mobileStatus.addEventListener('click',()=>button.click());
  }
  const dialog=document.createElement('dialog');
  dialog.id='vx-live-dialog';
  dialog.className='vx-live-dialog';
  dialog.setAttribute('aria-labelledby','vx-live-title');
  dialog.innerHTML=`<div class="vx-live-panel">
    <div class="vx-live-panel-top">
      <div><span class="vx-live-kicker">VAINAH VPN · СТАТУС</span>
      <h2 id="vx-live-title">Доступность оформления</h2></div>
      <button type="button" class="vx-live-close" data-live-close aria-label="Закрыть">×</button>
    </div>
    <p class="vx-live-explain">Проверка настроек касс без покупки, списания денег и входа в аккаунт.</p>
    <div class="vx-live-services" role="status" aria-live="polite">
      <div><strong>RollyPay</strong><span data-live-rolly>Не проверено</span></div>
      <div><strong>Platega</strong><span data-live-platega>Не проверено</span></div>
      <div><strong>Выдача доступа</strong><span data-live-delivery>Не проверено</span></div>
    </div>
    <p class="vx-live-note" data-live-message>Нажми «Проверить», чтобы получить данные сервера.</p>
    <div class="vx-live-actions">
      <button type="button" class="vx-live-recheck" data-live-recheck>Проверить</button>
      <a href="https://vainahvpn-python-preview.onrender.com/checkout.html">Выбрать тариф и оплату ↗</a>
    </div>
    <p class="vx-live-footnote">«Готова» означает, что сервер разрешает создание счёта. Это не подтверждение успешного платежа или работы VPN-туннеля.</p>
  </div>`;
  document.body.append(dialog);
  const close=dialog.querySelector('[data-live-close]');
  const check=dialog.querySelector('[data-live-recheck]');
  const note=dialog.querySelector('[data-live-message]');
  const labels={
    rolly:dialog.querySelector('[data-live-rolly]'),
    platega:dialog.querySelector('[data-live-platega]'),
    delivery:dialog.querySelector('[data-live-delivery]')
  };
  let controller=null,requestId=0;
  const apiOrigin=['https://vainahvpn.online','https://www.vainahvpn.online',
    'https://vainahvpn.onrender.com'].includes(location.origin)
    ?'https://vainahvpn-python-preview.onrender.com':'';
  function write(label,ready){
    label.textContent=ready?'Готова':'Недоступна';
    label.dataset.ready=String(ready);
  }
  async function refresh(){
    const id=++requestId;
    if(controller)controller.abort();
    controller=new AbortController();
    check.disabled=true;
    note.textContent='Проверяем актуальные настройки…';
    const timeout=setTimeout(()=>controller.abort(),8500);
    try{
      const response=await fetch(apiOrigin+'/api/shop/config',{
        method:'GET',headers:{Accept:'application/json'},cache:'no-store',
        credentials:'omit',signal:controller.signal
      });
      if(!response.ok)throw Error('HTTP '+response.status);
      const data=await response.json();
      if(!data||typeof data!=='object'||typeof data.checkout_ready!=='boolean'||
         typeof data.platega_ready!=='boolean')throw Error('INVALID_RESPONSE');
      if(id!==requestId)return;
      write(labels.rolly,data.checkout_ready===true);
      write(labels.platega,data.platega_ready===true);
      write(labels.delivery,data.provisioning_ready===true);
      note.textContent='Проверка завершена. Выбери доступную кассу на странице оплаты.';
    }catch{
      if(id!==requestId)return;
      for(const label of Object.values(labels)){
        label.textContent='Нет данных';
        delete label.dataset.ready;
      }
      note.textContent='Не удалось получить статус. Проверь интернет или повтори запрос.';
    }finally{
      clearTimeout(timeout);
      if(id===requestId){check.disabled=false;controller=null;}
    }
  }
  function hide(){
    requestId++;
    if(controller){controller.abort();controller=null;}
    if(typeof dialog.close==='function'&&dialog.open)dialog.close();
    else dialog.removeAttribute('open');
    button.focus();
  }
  button.addEventListener('click',()=>{
    if(typeof dialog.showModal==='function')dialog.showModal();
    else dialog.setAttribute('open','');
    void refresh();
  });
  check.addEventListener('click',()=>void refresh());
  close.addEventListener('click',hide);
  dialog.addEventListener('click',event=>{if(event.target===dialog)hide();});
  dialog.addEventListener('close',()=>{
    requestId++;if(controller){controller.abort();controller=null;}
  });
})();
