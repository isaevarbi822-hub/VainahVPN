/* Operator key is ephemeral and is sent only in a same-origin request header. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const keyInput=$('operator-key'),open=$('operator-load'),lock=$('operator-lock'),
    status=$('operator-status'),list=$('operator-list'),
    search=$('operator-search'),filter=$('operator-filter'),refresh=$('operator-refresh'),
    summary=$('operator-summary');
  if(!keyInput||!open||!lock)return;
  let key='',revision=0,ticketsCache=[];
  const node=(tag,cls,value)=>{
    const element=document.createElement(tag);element.className=cls;
    element.textContent=value||'';return element;
  };
  function clear(){
    revision++;key='';keyInput.value='';ticketsCache=[];
    if(search)search.value='';if(filter)filter.value='all';if(refresh)refresh.disabled=true;
    if(summary)summary.textContent='Статистика доступна после входа.';
    list.replaceChildren(node('p','vs-muted','Заявки скрыты до авторизации оператора.'));
    status.textContent='Доступ закрыт. Ключ удалён из формы.';
  }
  async function request(path,options={}){
    // Always merge request headers last. Spreading options AFTER headers
    // replaced the operator key on POST replies (403 SUPPORT_OPERATOR_FORBIDDEN).
    const {headers:extraHeaders,...requestOptions}=options;
    const response=await fetch(path,{
      method:'GET',cache:'no-store',credentials:'omit',
      ...requestOptions,
      headers:{Accept:'application/json','X-Vainah-Support-Key':key,
        ...(extraHeaders||{})}
    });
    const body=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(
      typeof body.detail==='string'?body.detail:'Ошибка ('+response.status+')'
    );
    return body;
  }
  function render(){
    const items=ticketsCache;
    const q=(search?.value||'').trim().toLocaleLowerCase('ru');
    const selected=filter?.value||'all';
    const counts={open:0,answered:0,closed:0,pending:0};
    for(const item of items){
      if(Object.hasOwn(counts,item.status))counts[item.status]++;
      if(item.notification_state==='pending')counts.pending++;
    }
    const tickets=items.filter(item=>{
      if(selected==='pending'?item.notification_state!=='pending':selected!=='all'&&item.status!==selected)return false;
      return !q||[item.id,item.category,item.message,item.reply,item.owner_reference]
        .some(value=>String(value||'').toLocaleLowerCase('ru').includes(q));
    });
    if(summary)summary.textContent='Последние '+items.length+' заявок · Открыты: '+counts.open+
      ' · С ответом: '+counts.answered+' · Закрыты: '+counts.closed+
      ' · Ожидают email: '+counts.pending+' · Показано: '+tickets.length;
    show(tickets);
  }
  function show(tickets){
    list.replaceChildren();
    if(!tickets.length){
      list.append(node('p','vs-muted','Обращений пока нет.'));
      return;
    }
    for(const ticket of tickets){
      if(!ticket||typeof ticket!=='object')continue;
      const card=node('article','vs-ticket','');
      card.append(node('strong','',String(ticket.id||'')));
      card.append(node('p','vs-muted','Тема: '+ticket.category+
        ' · Статус: '+ticket.status+' · Владелец: '+ticket.owner_reference));
      card.append(node('p','vs-user-message',String(ticket.message||'').slice(0,1500)));
      if(ticket.reply)card.append(node('p','vs-reply','Ответ: '+String(ticket.reply).slice(0,1500)));
      const delivery=String(ticket.notification_state||'none');
      const mailHint=node('p','vs-muted',ticket.email_notifications===true
        ?(delivery==='sent'?'Email-уведомление отправлено через Resend.'
          :delivery==='pending'?'Email ожидает отправки. Повторная попытка доступна спустя 2 минуты.'
          :'Клиент включил email-уведомления.')
        :'Email-уведомления отключены клиентом.');
      card.append(mailHint);
      if(delivery==='pending'&&ticket.email_notifications===true){
        const retry=node('button','vs-notification-button','Повторить отправку письма');
        retry.type='button';
        retry.addEventListener('click',async()=>{
          retry.disabled=true;
          try{
            const result=await request(
              '/api/support/operator/tickets/'+encodeURIComponent(ticket.id)+'/retry-email',
              {method:'POST'}
            );
            status.textContent=result.notification==='sent'
              ?'Письмо с уведомлением отправлено.'
              :'Отправка письма пока не подтверждена. Проверь Resend и попробуй позже.';
            await load();
          }catch(error){
            status.textContent='Не удалось повторить письмо: '+error.message;
          }finally{retry.disabled=false;}
        });
        card.append(retry);
      }
      const form=node('form','','');
      const textarea=node('textarea','','');
      textarea.rows=3;textarea.maxLength=1500;textarea.minLength=2;
      textarea.required=true;textarea.placeholder='Ответ клиенту без ссылок и секретов';
      const state=node('select','','');
      for(const [value,label] of [['answered','Ответить'],['closed','Ответить и закрыть']]){
        const option=node('option','',label);option.value=value;state.append(option);
      }
      const button=node('button','','Отправить ответ');
      button.type='submit';
      const feedback=node('p','vs-muted','');
      form.append(textarea,state,button,feedback);
      form.addEventListener('submit',async event=>{
        event.preventDefault();
        const current=revision;button.disabled=true;
        try{
          const result=await request('/api/support/operator/tickets/'+encodeURIComponent(ticket.id)+'/reply',{
            method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({reply:textarea.value.trim(),status:state.value})
          });
          if(current!==revision)return;
          const deliveryMessage=result.notification==='sent'
            ?' Уведомление отправлено на подтверждённую почту.'
            :result.notification==='pending'
              ?' Письмо пока не доставлено. Можно повторить отправку позже.'
              :' Email-уведомление не запрошено или уже отправлялось.';
          feedback.textContent='Ответ сохранён. Клиент увидит его в истории.'+deliveryMessage;
          await load();
          if(current===revision)status.textContent='Ответ сохранён.'+deliveryMessage;
        }catch(error){
          if(current===revision)feedback.textContent='Не удалось ответить: '+error.message;
        }finally{button.disabled=false;}
      });
      card.append(form);list.append(card);
    }
  }
  async function load(){
    if(!key)return;
    const current=revision;open.disabled=true;
    status.textContent='Проверяем доступ оператора…';
    try{
      const result=await request('/api/support/operator/tickets');
      if(current!==revision)return;
      ticketsCache=Array.isArray(result.items)?result.items:[];
      if(refresh)refresh.disabled=false;
      render();
      status.textContent='Авторизация оператора подтверждена. Заявки загружены.';
    }catch(error){
      if(current!==revision)return;
      status.textContent='Доступ не подтверждён: '+error.message;
      list.replaceChildren();ticketsCache=[];
      if(refresh)refresh.disabled=true;
      if(summary)summary.textContent='Статистика доступна после входа.';
      key='';keyInput.value='';
    }finally{open.disabled=false;}
  }
  if(search)search.addEventListener('input',()=>{if(key)render();});
  if(filter)filter.addEventListener('change',()=>{if(key)render();});
  if(refresh)refresh.addEventListener('click',()=>{if(key)void load();});
  open.addEventListener('click',()=>{
    const entered=keyInput.value;
    if(entered.length<40){
      status.textContent='Ключ оператора должен содержать не менее 40 символов.';
      return;
    }
    key=entered;keyInput.value='';revision++;
    void load();
  });
  lock.addEventListener('click',clear);
  window.addEventListener('pagehide',clear);
})();