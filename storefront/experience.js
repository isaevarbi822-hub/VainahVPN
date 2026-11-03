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
    const checks=[
      {id:'database',endpoint:'database-health',ok:'База отвечает, таблицы найдены',bad:'База недоступна или не готова'},
      {id:'h1',endpoint:'h1-panel-health',ok:'API-панель отвечает',bad:'Не удалось подтвердить доступность панели'},
      {id:'rollypay',endpoint:'rollypay-health',ok:'Ключ API принят',bad:'Проверка API не пройдена'},
      {id:'webhook',endpoint:'rollypay-webhook-health',ok:'Локальная проверка подписи работает',bad:'Подпись не настроена или тест не пройден'}
    ];
    const button=$('[data-status-refresh]',pageStatus);
    const updated=$('[data-status-updated]',pageStatus);
    async function checkOne(check){
      const element=$('[data-status-card="'+check.id+'"]',pageStatus);
      const badge=$('[data-status-label]',element);
      const detail=$('[data-status-detail]',element);
      badge.dataset.kind='unknown';badge.textContent='Проверяем';
      detail.textContent='Ожидаем ответ серверной функции…';
      const controller=new AbortController();
      const timer=setTimeout(()=>controller.abort(),9500);
      try{
        const response=await fetch('/.netlify/functions/'+check.endpoint,{
          method:'GET',cache:'no-store',credentials:'omit',
          signal:controller.signal,headers:{Accept:'application/json'}
        });
        const data=await response.json();
        const ok=data&&data.ok===true&&response.ok;
        badge.dataset.kind=ok?'ok':'problem';
        badge.textContent=ok?'Проверка пройдена':'Есть проблема';
        detail.textContent=ok?check.ok:check.bad;
        if(check.id==='h1'&&!ok && data.reason){
          const causes={
            connection_failed:'Соединение или таймаут',
            server_error:'Ошибка сервера H1Cloud',
            rate_limited:'Временное ограничение запросов',
            invalid_response:'Неожиданный ответ панели',
            api_error:'Ошибка API',
            unknown_error:'Причина не определена'
          };
          detail.textContent+=' · '+(causes[data.reason]||'Причина уточняется');
        }
        if(check.id==='webhook'&&ok){
          detail.textContent+=' · Это не подтверждает получение callback от RollyPay';
        }
        return ok;
      }catch{
        badge.dataset.kind='unknown';badge.textContent='Нет данных';
        detail.textContent='Не удалось загрузить результат. Это не доказывает неисправность сервиса.';
        return false;
      }finally{clearTimeout(timer)}
    }
    async function refresh(){
      button.disabled=true;
      button.textContent='Проверяем сервисы…';
      updated.textContent='Идёт проверка. Это разовый запрос, не постоянный мониторинг.';
      try{
        const answers=await Promise.all(checks.map(checkOne));
        updated.textContent='Последняя попытка проверки: '+new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})+
          '. Успешно: '+answers.filter(Boolean).length+' из '+answers.length+'.';
      }finally{
        button.disabled=false;button.textContent='↻ Обновить статусы';
      }
    }
    button.addEventListener('click',refresh);
    refresh();
  }

  const launch=$('[data-checkout-message]');
  if(launch){
    fetch('/.netlify/functions/subscription-plans',{cache:'no-store',credentials:'omit'})
      .then(r=>r.ok?r.json():Promise.reject(Error('plans')))
      .then(data=>{
        launch.textContent=data.checkoutReady===true?
          'Онлайн-оформление доступно после входа через Telegram.':
          'Онлайн-оплата пока отключена. Тарифы можно изучить без списаний.';
      })
      .catch(()=>{
        launch.textContent='Проверить доступность онлайн-оплаты можно на странице тарифов.';
      });
  }
})();
