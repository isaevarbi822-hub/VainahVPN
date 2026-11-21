/* A local troubleshooting assistant: no VPN credentials or diagnostics leave the browser. */
(() => {
  'use strict';
  const root=document.getElementById('repair-wizard');
  if(!root)return;
  const issue=root.querySelector('#repair-issue');
  const platform=root.querySelector('#repair-platform');
  const result=root.querySelector('#repair-result');
  const run=root.querySelector('#repair-run');
  const reset=root.querySelector('#repair-reset');
  const copy=root.querySelector('#repair-copy');
  const cases={
    import:{
      title:'VPN-ссылка не импортируется',
      steps:[
        'Открой личный кабинет и нажми «Получить VPN-ссылку» после подтверждённой выдачи.',
        'Убедись, что ссылка скопирована целиком. Не вставляй её в поисковую строку браузера.',
        'Обнови совместимое VPN-приложение и попробуй его функцию импорта подписки.',
        'Если ошибка остаётся, открой мастер подключения для своего устройства.'
      ],links:[['account.html','Мой VPN'],['device-center.html','Мастер подключения']]
    },
    connect:{
      title:'VPN не подключается',
      steps:[
        'Проверь, есть ли обычный интернет без VPN.',
        'В личном кабинете проверь выдачу и срок подписки, а также состояние H1Cloud.',
        'Перезапусти VPN-клиент и попробуй заново импортировать выданную подписку.',
        'Запусти безопасную проверку сети. Она не включает VPN автоматически.'
      ],links:[['network-check.html','Проверить сеть'],['account.html','Статус подписки']]
    },
    slow:{
      title:'VPN работает медленно',
      steps:[
        'Запусти тест скорости с VPN и без VPN в одной сети.',
        'Сравни задержку и скорость: маленькие отличия могут объясняться сервером теста.',
        'Проверь, не загружает ли другое приложение большие файлы.',
        'Выбери другую доступную локацию в VPN-клиенте и повтори проверку.'
      ],links:[['speed.html','Speed Lab'],['servers.html','Локации']]
    },
    payment:{
      title:'Оплата прошла, но ключа нет',
      steps:[
        'Не создавай повторный платёж сразу.',
        'Открой личный кабинет с тем же подтверждённым email, который использовал при покупке.',
        'Проверь историю заказа и письмо с подтверждением.',
        'Если выдача задерживается, обратись в поддержку с номером заказа без банковских данных и VPN-ключа.'
      ],links:[['account.html','История заказов'],['contact.html','Поддержка']]
    },
    email:{
      title:'Не приходит код входа',
      steps:[
        'Проверь правильность адреса email.',
        'Посмотри папки «Спам», «Промоакции» и «Все письма».',
        'Не запрашивай много кодов подряд. Используй только последний актуальный код.',
        'Проверь доступность email-входа и при необходимости обратись в поддержку.'
      ],links:[['network-check.html','Проверка сервисов'],['contact.html','Поддержка']]
    }
  };
  const platformNote={
    android:'Android: проверь разрешение на VPN и импорт в клиенте.',
    ios:'iPhone / iPad: при первом запуске разреши создание VPN-конфигурации.',
    windows:'Windows: проверь, что приложение запущено с нужными системными разрешениями.',
    mac:'macOS: проверь разрешения системного VPN в настройках.'
  };
  let summary='';
  function paint(){
    const info=cases[issue.value];
    const note=platformNote[platform.value]||'';
    if(!info){result.hidden=true;copy.disabled=true;return;}
    result.replaceChildren();
    const title=document.createElement('h2');
    title.textContent=info.title;
    const details=document.createElement('p');
    details.textContent=note;
    const list=document.createElement('ol');
    for(const step of info.steps){
      const li=document.createElement('li');li.textContent=step;list.append(li);
    }
    const links=document.createElement('div');links.className='repair-links';
    for(const [href,label] of info.links){
      const a=document.createElement('a');a.href=href;a.textContent=label+' →';links.append(a);
    }
    const foot=document.createElement('p');
    foot.className='repair-privacy';
    foot.textContent='Не отправляй никому свою VPN-ссылку, код входа или платёжные реквизиты.';
    result.append(title,details,list,links,foot);
    result.hidden=false;
    summary='Vainah VPN — '+info.title+'\n'+note+'\n'+
      info.steps.map((s,i)=>(i+1)+'. '+s).join('\n')+
      '\nНе передавай VPN-ссылку или код входа.';
    copy.disabled=false;
  }
  run.addEventListener('click',paint);
  reset.addEventListener('click',()=>{
    issue.selectedIndex=0;platform.selectedIndex=0;summary='';
    result.hidden=true;copy.disabled=true;
  });
  copy.addEventListener('click',async()=>{
    if(!summary)return;
    try{
      await navigator.clipboard.writeText(summary);
      copy.textContent='Скопировано ✓';
    }catch{
      copy.textContent='Не удалось скопировать';
    }
  });
  for(const select of [issue,platform])select.addEventListener('change',()=>{
    copy.textContent='Скопировать инструкцию';
    if(!result.hidden)paint();
  });
})();
