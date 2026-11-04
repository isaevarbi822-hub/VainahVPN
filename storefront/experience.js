/* Enhanced site tools: tariff comparison and read-only diagnostics. */
(function(){
  'use strict';
  function $(s,root=document){return root.querySelector(s)}
  function $$(s,root=document){return [...root.querySelectorAll(s)]}
  const formatter=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2});
  const compare=$('[data-compare]');
  if(compare){
    const device=$('[data-devices-filter]',compare);
    const duration=$('[data-duration-filter]',compare);
    const order=$('[data-sort-filter]',compare);
    const count=$('[data-compare-count]',compare);
    const empty=$('[data-compare-empty]',compare);
    const grid=$('[data-compare-grid]',compare);
    const cards=$$('[data-plan-days][data-plan-kopeks][data-plan-devices]',grid);
    function update(){
      const d=device.value,t=duration.value,sort=order.value;
      const visible=cards.filter(card=>{
        const days=Number(card.dataset.planDays),devices=Number(card.dataset.planDevices);
        const matchDevices=d==='all'||String(devices)===d;
        const matchDuration=t==='all'||(t==='short'?days<=90:days>=180);
        card.hidden=!(matchDevices&&matchDuration);
        return !card.hidden;
      });
      visible.sort((a,b)=>{
        const aCost=Number(a.dataset.planKopeks),bCost=Number(b.dataset.planKopeks);
        const aDays=Number(a.dataset.planDays),bDays=Number(b.dataset.planDays);
        return sort==='total'?aCost-bCost:
          sort==='value'?aCost/aDays-bCost/bDays:aDays-bDays;
      });
      for(const card of visible)grid.append(card);
      count.textContent=visible.length+' из '+cards.length+' тарифов';
      empty.hidden=visible.length>0;
    }
    for(const control of [device,duration,order])control.addEventListener('change',update);
    update();
  }

  const pageStatus=$('[data-service-status]');
  if(pageStatus){
    const checks=['database','h1','rollypay','webhook'];
    const button=$('[data-status-refresh]',pageStatus);
    const updated=$('[data-status-updated]',pageStatus);
    async function refresh(){
      button.disabled=true;
      button.textContent='Проверяем сервисы…';
      updated.textContent='Проверяем доступность API H1Cloud/RollyPay в режиме чтения. Подписка не создаётся.';
      try{
        const response=await fetch('/api/site/services',{
          method:'GET',cache:'no-store',headers:{Accept:'application/json'}
        });
        if(!response.ok)throw Error('API '+response.status);
        const data=await response.json();
        if(!data||!data.services)throw Error('Некорректный формат');
        let okCount=0;
        for(const id of checks){
          const element=$('[data-status-card="'+id+'"]',pageStatus);
          if(!element)continue;
          const badge=$('[data-status-label]',element);
          const detail=$('[data-status-detail]',element);
          const item=data.services[id];
          if(item&&item.status==='ok'){
            badge.dataset.kind='ok';badge.textContent='Проверка пройдена';okCount++;
          }else if(item&&item.status==='sandbox'){
            badge.dataset.kind='unknown';badge.textContent='Тестовый режим';
          }else if(item&&item.status==='configured'){
            badge.dataset.kind='unknown';badge.textContent='Настроено';
          }else if(item&&item.status==='error'){
            badge.dataset.kind='unknown';badge.textContent='Ошибка доступа';
          }else if(item&&item.status==='unavailable'){
            badge.dataset.kind='unknown';badge.textContent='Связь не подтверждена';
          }else{
            badge.dataset.kind='unknown';badge.textContent='Не подключено';
          }
          detail.textContent=item&&item.message?item.message:'Нет подтверждённых данных.';
        }
        updated.textContent='Проверено: '+new Date().toLocaleTimeString('ru-RU',{
          hour:'2-digit',minute:'2-digit'
        })+'. Подтверждённых работающих сервисов: '+okCount+' из '+checks.length+
        '. Неподключённые сервисы не считаются неисправными.';
      }catch(err){
        for(const id of checks){
          const element=$('[data-status-card="'+id+'"]',pageStatus);
          if(!element)continue;
          const badge=$('[data-status-label]',element);
          const detail=$('[data-status-detail]',element);
          badge.dataset.kind='unknown';badge.textContent='Нет данных';
          detail.textContent='Python API не ответил. Проверь запуск локального сайта.';
        }
        updated.textContent='Не удалось получить данные с Python-сервера: '+err.message;
      }finally{
        button.disabled=false;button.textContent='↻ Обновить статусы';
      }
    }
    button.addEventListener('click',refresh);
    refresh();
  }

  const launch=$('[data-checkout-message]');
  if(launch){
    fetch('/api/shop/config',{cache:'no-store',credentials:'omit'})
      .then(r=>r.ok?r.json():Promise.reject(Error('plans')))
      .then(data=>{
        launch.textContent=data.checkout_ready===true?
          'Онлайн-оформление доступно после входа через Telegram.':
          'Онлайн-оплата пока отключена. Тарифы можно изучить без списаний.';
      })
      .catch(()=>{
        launch.textContent='Проверить доступность онлайн-оплаты можно на странице тарифов.';
      });
  }
})();
