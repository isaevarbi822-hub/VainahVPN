/* Vainah account extras. No private data is stored in localStorage. */
(() => {
  'use strict';
  const kind=document.body.dataset.vainahFeature;
  const panel=document.getElementById('feature-main');
  const status=document.getElementById('feature-status');
  if(!panel || !status || !['referrals','rewards','gifts','notifications'].includes(kind))return;
  let revision=0;
  function el(tag,text='',className=''){
    const item=document.createElement(tag);
    item.textContent=String(text);
    if(className)item.className=className;
    return item;
  }
  function message(value,error=false){
    status.textContent=value;
    status.classList.toggle('error',error);
  }
  function metric(value,label){
    const box=el('div','','stat');
    box.append(el('strong',String(value)),el('small',label));
    return box;
  }
  function statRow(items){
    const row=el('div','','stats');
    for(const [n,label] of items)row.append(metric(n,label));
    return row;
  }
  async function api(path,options={}){
    const response=await fetch(path,{
      method:'GET',credentials:'same-origin',cache:'no-store',
      headers:{Accept:'application/json',...(options.headers||{})},
      ...options
    });
    const body=await response.json().catch(()=>({}));
    if(!response.ok){
      const error=new Error('Запрос не выполнен');
      error.status=response.status;
      throw error;
    }
    return body;
  }
  async function submit(path,payload){
    return api(path,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)
    });
  }
  function genericTitle(title,description){
    panel.replaceChildren(el('h2',title),el('p',description,'note'));
  }
  function action(text,handler,secondary=false){
    const button=el('button',text,secondary?'secondary':'');
    button.type='button';
    button.addEventListener('click',async()=>{
      button.disabled=true;
      try{await handler();}catch{message('Не удалось выполнить операцию. Проверь данные и попробуй снова.',true);}
      finally{button.disabled=false;}
    });
    return button;
  }
  function referralPanel(data){
    genericTitle('Моя реферальная ссылка',
      'Привязка приглашённого подтверждается после входа. Бонусы не выдаются до запуска программы и проверки покупки.');
    panel.append(statRow([
      [data.invited_count??0,'Приглашений'],
      [data.qualified_paid_count??0,'Покупки подтверждены'],
      [data.redemption_enabled?'Активны':'Ожидают запуска','Бонусы']
    ]));
    panel.append(el('p','Твой код: '+String(data.referral_code||'—'),'note'));
    const share=el('input');
    share.type='text';share.readOnly=true;
    const sharePath=typeof data.share_path==='string' &&
      /^\/referrals\.html\?ref=VN[A-F0-9]{18}$/.test(data.share_path)
      ?data.share_path:null;
    share.value=sharePath?new URL(sharePath,location.origin).href:'';
    share.setAttribute('aria-label','Моя ссылка приглашения');
    const wrap=el('div','','row');
    wrap.append(share,action('Скопировать ссылку',async()=>{
      if(!share.value)throw Error('NO_LINK');
      try{
        await navigator.clipboard.writeText(share.value);
        message('Ссылка скопирована.');
      }catch{
        share.focus();share.select();message('Выделенную ссылку можно скопировать вручную.');
      }
    }));
    panel.append(wrap);
    const form=el('form');
    form.append(el('h2','Ввести код приглашения'));
    const invited=new URLSearchParams(location.search).get('ref');
    const code=el('input');
    code.placeholder='VN…';code.maxLength=20;code.required=true;
    code.value=invited && /^VN[A-F0-9]{18}$/.test(invited)?invited:'';
    code.setAttribute('aria-label','Реферальный код');
    const btn=el('button','Привязать приглашение');
    btn.type='submit';
    const row=el('div','','row');row.append(code,btn);form.append(row);
    if(data.joined_referral)form.append(el('p','Приглашение уже привязано к аккаунту.','note'));
    form.addEventListener('submit',async event=>{
      event.preventDefault();
      const value=code.value.trim().toUpperCase();
      if(!/^VN[A-F0-9]{18}$/.test(value)){message('Неверный формат кода.',true);return;}
      btn.disabled=true;
      try{
        await submit('/api/account/growth/referrals/claim',{code:value});
        message('Приглашение сохранено. Бонус не начисляется автоматически.');
        await load();
      }catch{message('Не удалось привязать. Код может быть чужим, уже использованным или привязанным к тебе.',true);}
      finally{btn.disabled=false;}
    });
    panel.append(form);
  }
  function rewardsPanel(data){
    genericTitle('Rewards — мои достижения',
      'Используются только оплаченные и выданные заказы, без тестовых. Баллы пока предварительные и не доступны для обмена.');
    panel.append(statRow([
      [data.eligible_purchase_count??0,'Подтверждённых покупок'],
      [data.potential_points??0,'Потенциальные баллы'],
      [data.redeemable_points??0,'Доступно к обмену']
    ]));
    panel.append(el('p','Предварительная формула: 10 баллов за подтверждённую покупку, 25 за подтверждённую покупку приглашённого друга.','warning'));
    panel.append(el('p','Программа не активирована. Обмен на дни VPN, деньги или скидки не проводится.','note'));
    const link=el('a','Перейти к приглашениям');link.href='referrals.html';panel.append(link);
  }
  function giftsPanel(data){
    genericTitle('Мои черновики подарков',
      'Сохрани желаемый тариф. Это не платёж, не подарочный код и не право доступа к VPN.');
    const form=el('form');
    const selector=el('select');selector.id='gift-plan';
    selector.setAttribute('aria-label','Тариф для будущего подарка');
    for(const [id,title] of [
      ['30','1 месяц'],['60','2 месяца'],['90','3 месяца'],
      ['180','6 месяцев'],['365','1 год'],['365-family','Семейный год']
    ]){
      const option=el('option',title);option.value=id;selector.append(option);
    }
    const save=el('button','Сохранить черновик');save.type='submit';
    const row=el('div','','row');row.append(selector,save);form.append(row);
    form.addEventListener('submit',async event=>{
      event.preventDefault();save.disabled=true;
      try{
        await submit('/api/account/growth/gifts/drafts',{plan_id:selector.value});
        message('Черновик сохранён. Платёж и VPN не создавались.');
        await load();
      }catch{message('Черновик не сохранился. Доступно максимум 5 черновиков в сутки.',true);}
      finally{save.disabled=false;}
    });
    panel.append(form,el('p','Покупка подарков и выдача активируемых кодов ещё не подключены.','warning'));
    const drafts=Array.isArray(data.drafts)?data.drafts:[];
    panel.append(el('h2','История черновиков'));
    if(!drafts.length)panel.append(el('p','Черновиков пока нет.','muted'));
    for(const item of drafts){
      const card=el('div','','notice');
      card.append(el('strong',item.plan_title||'Подписка'),
        el('p','Статус: черновик, не оплачен. Код активации не создан.'));
      panel.append(card);
    }
  }
  function notificationsPanel(data){
    genericTitle('Уведомления моего аккаунта',
      'События рассчитываются из доступных данных подписки. Статус прочтения сохраняется только для твоего аккаунта.');
    panel.append(statRow([[data.unread_count??0,'Непрочитанных'],
      [Array.isArray(data.items)?data.items.length:0,'Всего актуальных событий'],
      ['Неактивны','Push-уведомления']]));
    const items=Array.isArray(data.items)?data.items:[];
    if(!items.length)panel.append(el('p','По проверенным данным срочных уведомлений нет. Это не гарантия доступности VPN.','note'));
    for(const item of items){
      if(!item||typeof item!=='object')continue;
      const card=el('article','','notice');
      card.append(el('strong',item.title||'Событие'),
        el('p',item.description||''),
        el('small',item.read?'Прочитано':'Новое','stamp'));
      if(/^\/(account|support-center)\.html$/.test(item.href||'')){
        const link=el('a','Открыть раздел');
        link.href=item.href;card.append(link,el('span','  '));
      }
      if(!item.read&&/^[a-f0-9]{64}$/.test(item.id||'')){
        card.append(action('Прочитано',async()=>{
          await submit('/api/account/notifications/read',{notification_id:item.id});
          await load();
        },true));
      }
      panel.append(card);
    }
  }
  async function load(){
    const current=++revision;
    message('Получаем данные подтверждённого аккаунта…');
    try{
      const endpoint=kind==='notifications'?'/api/account/notifications':'/api/account/growth';
      const data=await api(endpoint);
      if(current!==revision)return;
      if(kind==='referrals')referralPanel(data);
      if(kind==='rewards')rewardsPanel(data);
      if(kind==='gifts')giftsPanel(data);
      if(kind==='notifications')notificationsPanel(data);
      message('Данные обновлены. Не передавай личные VPN-ссылки.');
    }catch(error){
      if(current!==revision)return;
      panel.replaceChildren(el('h2','Данные недоступны'),
        el('p',error.status===401?'Требуется вход с подтверждённой почтой.':
          'Не удалось получить данные. Возможно, временно недоступна база данных.','muted'));
      const login=el('a','Открыть личный кабинет');
      login.href='account.html';panel.append(login);
      message(error.status===401?'Вход необходим.':'Не удалось загрузить раздел.',true);
    }
  }
  void load();
})();
