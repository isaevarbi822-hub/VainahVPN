/* Authenticated support tickets; all user and operator text rendered via textContent. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const status=$('vs-status'),form=$('vs-form'),submit=$('vs-submit');
  const list=$('vs-tickets'),refresh=$('vs-refresh');
  const message=$('vs-message'),category=$('vs-category'),counter=$('vs-counter');
  if(!form||!submit||!list)return;
  const labels={connection:'Подключение',payment:'Оплата и подписка',
    account:'Вход и аккаунт',other:'Другое'};
  const statusNames={open:'Открыто',answered:'Есть ответ',closed:'Закрыто'};
  let ready=false,authenticated=false,loading=false;
  const note=value=>{status.textContent=value};
  async function request(url,options={}){
    const response=await fetch(url,{credentials:'same-origin',cache:'no-store',
      headers:{Accept:'application/json',...(options.headers||{})},...options});
    const body=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(
      typeof body.detail==='string'?body.detail:'Ошибка сервера ('+response.status+')'
    );
    return body;
  }
  const label=(tag,cls,text)=>{
    const element=document.createElement(tag);element.className=cls;
    element.textContent=String(text||'');return element;
  };
  const prettyDate=value=>{
    const date=new Date(value);
    return Number.isFinite(date.getTime())?
      new Intl.DateTimeFormat('ru-RU',{dateStyle:'medium',timeStyle:'short'}).format(date):'Дата неизвестна';
  };
  function render(tickets){
    list.replaceChildren();
    if(!tickets.length){
      list.append(label('p','vs-muted','Обращений пока нет.'));
      return;
    }
    for(const ticket of tickets){
      if(!ticket||typeof ticket!=='object')continue;
      const card=label('article','vs-ticket','');
      const head=label('div','vs-ticket-head','');
      head.append(label('strong','',labels[ticket.category]||'Обращение'));
      head.append(label('span','vs-state',statusNames[ticket.status]||'Уточняется'));
      card.append(head);
      card.append(label('small','vs-muted','Заявка '+String(ticket.id||'').slice(0,30)+
        ' · '+prettyDate(ticket.created_at)));
      card.append(label('p','vs-user-message',String(ticket.message||'').slice(0,1500)));
      if(ticket.reply){
        const response=label('div','vs-reply','');
        response.append(label('strong','','Ответ поддержки'));
        response.append(label('p','',String(ticket.reply).slice(0,1500)));
        card.append(response);
      }
      list.append(card);
    }
  }
  async function load(){
    if(!authenticated)return;
    refresh.disabled=true;
    try{
      const response=await request('/api/support/tickets');
      render(Array.isArray(response.items)?response.items:[]);
    }catch(error){
      list.replaceChildren(label('p','vs-muted','Не удалось получить историю: '+error.message));
    }finally{refresh.disabled=false;}
  }
  async function init(){
    try{
      const [config,telegram,email]=await Promise.all([
        request('/api/support/config'),
        request('/api/telegram/account').catch(()=>({authenticated:false})),
        request('/api/email-auth/account').catch(()=>({authenticated:false}))
      ]);
      ready=config.available===true;
      authenticated=telegram.authenticated===true||email.authenticated===true;
      if(!authenticated){
        note('Для создания и просмотра обращений сначала войди в личный кабинет.');
        const signIn=label('a','vs-strong-link','Войти в кабинет');
        signIn.href='account.html';status.append(' ',signIn);
      }else if(!ready){
        note('Центр заявок ещё не настроен оператором. Используй Telegram @VainahSupport.');
      }else note('Вход подтверждён. Можно создать обращение и просмотреть историю.');
      submit.disabled=!ready||!authenticated;
      refresh.disabled=!authenticated;
      if(authenticated)void load();
    }catch(error){
      note('Не удалось проверить настройки поддержки: '+error.message);
    }
  }
  message.addEventListener('input',()=>{counter.textContent=message.value.length+' / 1500'});
  refresh.addEventListener('click',load);
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(!ready||!authenticated||loading)return;
    loading=true;submit.disabled=true;
    try{
      const response=await request('/api/support/tickets',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({category:category.value,message:message.value.trim()})
      });
      message.value='';counter.textContent='0 / 1500';
      note('Обращение '+response.id+' принято. Ответ появится в истории после ответа оператора.');
      await load();
    }catch(error){
      note('Обращение не отправлено: '+error.message+
        '. Не повторяй отправку, если не уверен в результате — сначала обнови историю.');
    }finally{
      loading=false;submit.disabled=!ready||!authenticated;
    }
  });
  void init();
})();