/* Authenticated support tickets; all user and operator text rendered via textContent. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const status=$('vs-status'),form=$('vs-form'),submit=$('vs-submit');
  const list=$('vs-tickets'),refresh=$('vs-refresh');
  const message=$('vs-message'),category=$('vs-category'),counter=$('vs-counter');
  const notifyToggle=$('vs-notify-email'),notifyHint=$('vs-notify-hint');
  if(!form||!submit||!list)return;
  const labels={connection:'Подключение',payment:'Оплата и подписка',
    account:'Вход и аккаунт',other:'Другое'};
  const statusNames={open:'Открыто',answered:'Есть ответ',closed:'Закрыто'};
  let ready=false,authenticated=false,loading=false;
  let emailNotificationsAvailable=false;
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
      const notices=label('div','vs-notification-row','');
      notices.append(label('span','vs-muted',ticket.email_notifications===true
        ?'Уведомления о следующих ответах включены.'
        :'Уведомления на почту выключены.'));
      if(emailNotificationsAvailable){
        const toggle=label('button','vs-notification-button',
          ticket.email_notifications===true?'Выключить письма':'Уведомлять по email');
        toggle.type='button';
        toggle.addEventListener('click',async()=>{
          toggle.disabled=true;
          try{
            await request('/api/support/tickets/'+encodeURIComponent(ticket.id)+'/email-notifications',{
              method:'POST',headers:{'Content-Type':'application/json'},
              body:JSON.stringify({enabled:ticket.email_notifications!==true})
            });
            note('Настройка уведомлений сохранена. Прошлые ответы повторно не рассылаются.');
            await load();
          }catch(error){
            note('Не удалось изменить уведомления: '+error.message+
              '. Для Telegram сначала подтверди почту в личном кабинете.');
          }finally{toggle.disabled=false;}
        });
        notices.append(toggle);
      }
      // Keep notification preference as the final ticket control.
      const threadButton=label('button','vs-notification-button','Показать переписку');
      threadButton.type='button';
      const timeline=label('div','vs-ticket-history','');
      timeline.hidden=true;
      threadButton.addEventListener('click',async()=>{
        if(!timeline.hidden){timeline.hidden=true;threadButton.textContent='Показать переписку';return;}
        threadButton.disabled=true;
        try{
          const response=await request('/api/support/tickets/'+encodeURIComponent(ticket.id)+'/messages');
          timeline.replaceChildren();
          for(const entry of Array.isArray(response.items)?response.items:[]){
            const row=label('div',entry.sender==='operator'?'vs-reply':'vs-user-message','');
            row.append(label('strong','',entry.sender==='operator'?'Поддержка':'Вы'));
            row.append(label('p','',String(entry.message||'').slice(0,1500)));
            timeline.append(row);
          }
          timeline.hidden=false;
          threadButton.textContent='Скрыть переписку';
        }catch(error){note('Не удалось открыть переписку: '+error.message);}
        finally{threadButton.disabled=false;}
      });
      card.append(threadButton,timeline);
      if(ticket.reply){
        const ratingForm=label('form','vs-rating','');
        const ratingSelect=label('select','','');
        ratingSelect.setAttribute('aria-label','Оценка работы поддержки');
        for(let star=5;star>=1;star--){
          const option=label('option','',star+' из 5');
          option.value=String(star);ratingSelect.append(option);
        }
        const ratingButton=label('button','vs-notification-button','Оценить ответ');
        ratingButton.type='submit';
        ratingForm.append(ratingSelect,ratingButton);
        ratingForm.addEventListener('submit',async event=>{
          event.preventDefault();ratingButton.disabled=true;
          try{
            await request('/api/support/tickets/'+encodeURIComponent(ticket.id)+'/rating',{
              method:'POST',headers:{'Content-Type':'application/json'},
              body:JSON.stringify({rating:Number(ratingSelect.value)})
            });
            note('Спасибо! Оценка ответа сохранена.');
          }catch(error){note('Не удалось сохранить оценку: '+error.message);}
          finally{ratingButton.disabled=false;}
        });
        card.append(ratingForm);
      }
      if(ticket.status!=='closed'){
        const followup=label('form','vs-followup','');
        const followText=label('textarea','','');
        followText.required=true;followText.minLength=4;followText.maxLength=1500;
        followText.rows=2;followText.placeholder='Дополнить обращение без VPN-ссылок и паролей';
        const followButton=label('button','vs-notification-button','Отправить уточнение');
        followButton.type='submit';
        followup.append(followText,followButton);
        followup.addEventListener('submit',async event=>{
          event.preventDefault();followButton.disabled=true;
          try{
            await request('/api/support/tickets/'+encodeURIComponent(ticket.id)+'/messages',{
              method:'POST',headers:{'Content-Type':'application/json'},
              body:JSON.stringify({message:followText.value.trim()})
            });
            note('Уточнение отправлено. Обращение снова открыто.');
            await load();
          }catch(error){note('Не удалось отправить уточнение: '+error.message);}
          finally{followButton.disabled=false;}
        });
        card.append(followup);
      }
      card.append(notices);
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
      emailNotificationsAvailable=config.email_notifications_available===true;
      authenticated=telegram.authenticated===true||email.authenticated===true;
      if(notifyToggle){
        notifyToggle.disabled=!emailNotificationsAvailable;
        if(!emailNotificationsAvailable)notifyToggle.checked=false;
      }
      if(notifyHint&&!emailNotificationsAvailable)
        notifyHint.textContent='Почтовая доставка временно не настроена. Ответы можно читать в истории заявок.';
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
        body:JSON.stringify({category:category.value,message:message.value.trim(),
          notify_email:emailNotificationsAvailable&&notifyToggle?.checked===true})
      });
      message.value='';counter.textContent='0 / 1500';
      note('Обращение '+response.id+' принято. Ответ появится в истории. '+
        (notifyToggle?.checked?'Если почта подтверждена, придёт уведомление.':''));
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