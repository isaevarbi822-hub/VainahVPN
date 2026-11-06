/* Vainah VPN public control hub and safe diagnostics.
   Read-only GET endpoints; no orders, subscriptions, tokens or payment actions. */
(() => {
  'use strict';
  const one=(s,root=document)=>root.querySelector(s);
  const all=(s,root=document)=>[...root.querySelectorAll(s)];
  const set=(e,v)=>{if(e)e.textContent=String(v)};
  const states={
    connection:['VPN не подключается','Проверь сначала соединение без VPN.',[
      'Проверь обычный интернет без VPN и перезапусти клиент.',
      'В кабинете проверь срок и наличие выданной конфигурации.',
      'Запусти проверку сети; результат API не гарантирует доступность VPN-туннеля.'
    ],'repair-wizard.html'],
    import:['Не импортируется ссылка','Не передавай персональную ссылку на другие сайты.',[
      'Скопируй подписку целиком из защищённого кабинета.',
      'Импортируй ссылку через функцию совместимого VPN-клиента.',
      'Попробуй обновить клиент и открой инструкцию для своего устройства.'
    ],'device-center.html'],
    slow:['Медленное соединение','Сравни показатели до одинакового сервера.',[
      'Измерь скорость с VPN и без VPN в одной и той же сети.',
      'Закрой фоновые загрузки и выбери другую доступную локацию.',
      'Используй Speed Lab: он проверяет веб-сервер Render, а не VPN-туннель.'
    ],'speed.html'],
    account:['Не удаётся войти в аккаунт','Для сайта используй подтверждённый email.',[
      'Войди с тем же email, который использовал при покупке.',
      'Проверь код в папках «Спам» и «Промоакции».',
      'Если письма нет, обратись в поддержку, не раскрывая код.'
    ],'account.html'],
    payment:['Оплата или заказ','Повторная покупка может привести к двойному счёту.',[
      'Не оплачивай повторно, пока не проверен исходный заказ.',
      'Открой личный кабинет и проверь историю и письмо с квитанцией.',
      'Если ключ не появился, сообщи поддержке номер заказа без банковских данных.'
    ],'account.html'],
    panel:['Панель H1Cloud недоступна','Состояние панели — не всегда состояние VPN-соединения.',[
      'Проверь статус сервисов и доступность веб-API.',
      'Не удаляй оплаченный заказ и не меняй конфигурацию без причины.',
      'Если проблема длится, обратись в поддержку.'
    ],'network-check.html']
  };
  function guidance(){
    const root=one('[data-diagnostics-center]');
    if(!root)return;
    const buttons=all('[data-diag-problem]',root),title=one('[data-diag-title]',root),
      summary=one('[data-diag-summary]',root),list=one('[data-diag-list]',root),
      link=one('[data-diag-link]',root);
    function draw(key){
      const entry=states[key];if(!entry)return;
      for(const b of buttons)b.setAttribute('aria-pressed',String(b.dataset.diagProblem===key));
      set(title,entry[0]);set(summary,entry[1]);
      if(list){list.replaceChildren();for(const [i,step] of entry[2].entries()){
        const li=document.createElement('li'),num=document.createElement('span'),info=document.createElement('div');
        set(num,String(i+1).padStart(2,'0'));set(info,step);li.append(num,info);list.append(li);
      }}
      if(link)link.href=entry[3];
    }
    for(const b of buttons)b.addEventListener('click',()=>draw(b.dataset.diagProblem));
    draw('connection');
  }
  async function get(path,controller){
    const timer=setTimeout(()=>controller.abort(),10000);
    try{
      const response=await fetch(path,{method:'GET',credentials:'omit',cache:'no-store',
        redirect:'error',headers:{Accept:'application/json'},signal:controller.signal});
      if(!response.ok)throw Error('HTTP '+response.status);
      return await response.json();
    }finally{clearTimeout(timer);}
  }
  function health(){
    const root=one('[data-diagnostics-center]');
    if(!root)return;
    const button=one('[data-diag-check]',root),badge=one('[data-diag-check-badge]',root),
      box=one('[data-diag-check-results]',root),copy=one('[data-diag-copy]',root),
      copyMessage=one('[data-diag-copy-status]',root);
    let running=null,report='';
    function row(name,ok,detail){
      const d=document.createElement('p');
      set(d,(ok===true?'✓ ':ok===false?'! ':'? ')+name+' — '+detail);
      box.append(d);
    }
    button?.addEventListener('click',async()=>{
      if(running)return;
      running=new AbortController();
      button.disabled=true;if(copy)copy.disabled=true;report='';
      box?.replaceChildren();
      if(badge){badge.dataset.level='neutral';set(badge,'Проверяем…');}
      const statuses=[];
      const add=(name,good,message)=>{
        statuses.push(name+': '+message);
        if(box)row(name,good,message);
      };
      try{
        const data=await get('/api/health',running);
        add('Python API',data?.ok===true,data?.ok===true?'Доступен':'Нет подтверждения');
      }catch{add('Python API',false,'Нет ответа');}
      if(running.signal.aborted){
        add('Другие сервисы',null,'Не проверены (время ожидания)');
      }else{
        try{
          const data=await get('/api/site/services',running),svc=data?.services||{};
          for(const [key,label] of [['database','PostgreSQL'],['h1','H1Cloud API'],['rollypay','RollyPay API']]){
            const code=svc[key]?.status;
            const good=code==='ok';
            add(label,good?true:code==null?null:false,
              good?'API отвечает':code==null?'Нет подтверждённых данных':'Недоступно или не настроено');
          }
          const wh=svc.webhook?.status;
          add('Webhook',wh==='configured'?true:null,
            wh==='configured'?'Подпись настроена (это не доставка платежа)':'Состояние не подтверждено');
        }catch{
          add('Проверка интеграций',false,'API статуса не ответил');
        }
      }
      report=['VAINAH VPN · Общая диагностика','Отчёт о разовых GET-запросах',...statuses,
        'Результаты не подтверждают подключение VPN или списание денег.'].join('\n');
      if(copy)copy.disabled=false;
      if(badge){
        badge.dataset.level=statuses.some(s=>s.includes('Нет ответа')||s.includes('Недоступно'))?'warn':'good';
        set(badge,'Проверка завершена');
      }
      button.disabled=false;running=null;
    });
    copy?.addEventListener('click',async()=>{
      if(!report)return;
      try{
        await navigator.clipboard.writeText(report);
        set(copyMessage,'Безопасный отчёт скопирован без VPN-ссылок и личных данных.');
      }catch{
        const field=document.createElement('textarea');
        field.readOnly=true;field.value=report;field.rows=7;
        field.setAttribute('aria-label','Отчёт диагностики для ручного копирования');
        box?.append(field);field.focus();field.select();
        set(copyMessage,'Браузер запретил копирование. Выдели и скопируй текст вручную.');
      }
    });
    window.addEventListener('pagehide',()=>running?.abort());
  }
  function hub(){
    const root=one('[data-control-hub]');
    if(!root)return;
    const badge=one('[data-hub-login-badge]',root);
    const userName=one('[data-hub-user-name]',root);
    const userDescription=one('[data-hub-user-description]',root);
    const loginMessage=one('[data-hub-login-message]',root);
    const statuses=all('[data-hub-check]',root);
    const updated=one('[data-hub-checked-at]',root),refresh=one('[data-hub-refresh]',root),
      planGrid=one('[data-hub-plans]',root),plansMessage=one('[data-hub-plans-message]',root);
    let revision=0,abort=null;
    async function run(){
      const number=++revision;
      abort?.abort();abort=new AbortController();
      if(refresh)refresh.disabled=true;
      set(updated,'Проверяем сервисы…');
      for(const item of statuses){
        const b=one('[data-check-badge]',item);if(b){b.dataset.level='neutral';set(b,'Проверяем…');}
      }
      const setStatus=(key,value,detail)=>{
        const cell=one('[data-hub-check="'+key+'"]',root);if(!cell)return;
        const badge=one('[data-check-badge]',cell);
        if(badge){badge.dataset.level=value==='ok'?'good':value?'warn':'neutral';
          set(badge,value==='ok'?'API отвечает':value?'Нет подтверждения':'Нет данных');}
        set(one('[data-check-detail]',cell),detail);
      };
      try{
        const data=await get('/api/site/services',abort);
        if(number!==revision)return;
        const svc=data?.services||{};
        for(const key of ['database','h1','rollypay','webhook']){
          const state=svc[key]?.status;
          setStatus(key,state,state==='ok'?'Read-only проверка успешна':
            state==='configured'?'Конфигурация присутствует (доставка не проверена)':
            state?'Проверка не подтвердила готовность':'Данные не получены');
        }
        set(updated,'Проверено. Доступность API не гарантирует, что VPN-туннель работает.');
      }catch{
        if(number===revision){
          for(const key of ['database','h1','rollypay','webhook'])setStatus(key,null,'API статуса недоступен');
          set(updated,'Сервисы не удалось проверить. Повтори запрос позднее.');
        }
      }finally{if(number===revision){if(refresh)refresh.disabled=false;}}
    }
    refresh?.addEventListener('click',run);
    (async()=>{
      try{
        // The account overview is owner-scoped on the server. Never fetch or
        // display the private subscription URL in this public hub.
        const response=await fetch('/api/account/overview',{
          method:'GET',credentials:'same-origin',cache:'no-store',
          headers:{Accept:'application/json'}
        });
        if(response.status===401){
          if(badge){badge.dataset.level='neutral';set(badge,'Требуется вход');}
          set(userName,'Добро пожаловать!');
          set(userDescription,'Для просмотра подписки войди с подтверждённым email.');
          set(loginMessage,'Личные покупки и VPN-доступ гостям не показываются.');
          return;
        }
        if(!response.ok)throw Error('ACCOUNT_UNAVAILABLE');
        const overview=await response.json();
        if(overview?.authenticated!==true)throw Error('ACCOUNT_INVALID');
        if(badge){badge.dataset.level='good';set(badge,'Вход подтверждён');}
        set(userName,'Личный кабинет');
        const orders=Array.isArray(overview.orders)?overview.orders:[];
        set(one('[data-hub-orders]',root),String(orders.length));
        const sub=overview.subscription;
        if(sub?.paid===true&&sub.status==='delivered'){
          set(one('[data-hub-plan]',root),sub.plan_title||'VPN-подписка');
          const expires=new Date(sub.expires_at);
          set(one('[data-hub-expires]',root),Number.isFinite(expires.getTime())?
            new Intl.DateTimeFormat('ru-RU').format(expires):'Не указана');
          set(one('[data-hub-devices]',root),Number.isSafeInteger(sub.device_limit)&&sub.device_limit>0?
            String(sub.device_limit):'—');
          set(userDescription,'В кабинете есть подтверждённая сервером подписка.');
          set(loginMessage,'Чтобы получить личный ключ и обновить данные, открой кабинет.');
        }else{
          set(one('[data-hub-plan]',root),'Нет активной выдачи');
          set(one('[data-hub-expires]',root),'—');
          set(one('[data-hub-devices]',root),'—');
          set(userDescription,'Покупка или действующая выдача пока не подтверждена.');
          set(loginMessage,'Посмотри историю в кабинете и проверь H1Cloud.');
        }
      }catch{
        if(badge){badge.dataset.level='neutral';set(badge,'Данные недоступны');}
        set(userName,'Состояние аккаунта неизвестно');
        set(userDescription,'Сервер не подтвердил сведения о подписке.');
        set(loginMessage,'Повтори попытку в личном кабинете.');
      }
    })();
    (async()=>{
      try{
        const response=await fetch('/api/shop/plans',{credentials:'omit',cache:'no-store'});
        if(!response.ok)throw Error('CATALOG');
        const body=await response.json();
        if(!Array.isArray(body?.items))throw Error('CATALOG');
        planGrid?.replaceChildren();
        for(const p of body.items){
          if(!p||typeof p.title!=='string'||!Number.isSafeInteger(p.kopeks))continue;
          const card=document.createElement('article');card.className='cx-plan-card';
          const name=document.createElement('h3');set(name,p.title);
          const price=document.createElement('strong');set(price,
            new Intl.NumberFormat('ru-RU').format(p.kopeks/100)+' ₽');
          const desc=document.createElement('p');set(desc,
            (p.days||'—')+' дней · до '+(p.devices||'—')+' устройств');
          const link=document.createElement('a');link.href='plans.html';set(link,'Выбрать тариф ↗');
          card.append(name,price,desc,link);planGrid?.append(card);
        }
        set(plansMessage,'Цены получены из публичного API; оплата проверяется отдельно.');
      }catch{set(plansMessage,'Каталог тарифов не загрузился. Открой страницу «Тарифы».');}
    })();
    void run();
  }
  guidance();health();hub();
})();