/* Vainah Repair Ultra: local, read-only troubleshooting guidance.
   No API calls, no account identifiers, no payment writes and no private VPN links. */
(() => {
  'use strict';
  const root=document.querySelector('[data-ultra-repair]');
  if(!root)return;

  const names={android:'Android',ios:'iPhone / iPad',windows:'Windows',macos:'Mac',linux:'Linux'};
  const issues={
    connect:{
      label:'VPN не подключается',
      summary:'Идём от простых проверок к настройкам клиента. Состояние веб-сайта не показывает работоспособность твоего VPN-туннеля.',
      steps:[
        'Проверь, что без VPN обычный интернет работает. При необходимости перезапусти Wi‑Fi или мобильное соединение.',
        'Убедись, что подписка активна в личном кабинете, а данные подключения импортированы в совместимый VPN-клиент.',
        'Проверь, не отключены ли разрешения VPN у самого приложения. Если устройство управляется организацией, соблюдай её правила.',
        'Открой инструкцию для своей платформы и повтори разрешённую процедуру подключения. Если проблема сохраняется, обратись в поддержку без передачи приватных ключей.'
      ],
      link:'connect'
    },
    import:{
      label:'Не импортируется подписка',
      summary:'Поможем проверить формат и совместимость клиента, не отправляя ключ на сайт.',
      steps:[
        'Сверь тип VPN-протокола, который поддерживает твой клиент, с инструкцией сервиса.',
        'Проверь, скопирована ли конфигурация полностью. Не отправляй её в публичные чаты или обращения.',
        'Обнови совместимый VPN-клиент из официального источника и попробуй повторный импорт по инструкции.',
        'Если ошибка осталась, сообщи поддержке модель устройства, версию приложения и текст ошибки без приватной ссылки.'
      ],
      link:'connect'
    },
    slow:{
      label:'Медленное соединение',
      summary:'Сравним соединение без VPN и с VPN и отделим локальную сеть от проблем приложения.',
      steps:[
        'Проверь загрузку обычной страницы без VPN: если она медленная, причина может быть в сети или сигнале.',
        'Посмотри, не выполняются ли загрузки, обновления или резервное копирование в фоне.',
        'Проверь отображаемую клиентом информацию о выбранном сервере. Показатель ping на сайте не является тестом твоего VPN.',
        'Если после разрешённых проверок скорость остаётся низкой, передай поддержке время, тип сети и общее описание проблемы.'
      ],
      link:'diagnostics'
    },
    account:{
      label:'Не получается войти',
      summary:'Проверим вход по почте и доступ к аккаунту без раскрытия кодов.',
      steps:[
        'Проверь адрес электронной почты, указанный при запросе кода, и папку «Спам».',
        'Убедись, что используешь актуальный код и что между запросами не осталось старых сообщений.',
        'Попробуй официальный способ входа, доступный на странице сайта. Не передавай одноразовый код другим людям.',
        'Если вход не восстанавливается, обратись к поддержке с примерным временем и общим описанием ошибки, не сообщая код или пароль.'
      ],
      link:'account'
    },
    payment:{
      label:'Оплата или выдача заказа',
      summary:'Первое правило — не платить повторно, пока неизвестен статус предыдущего заказа.',
      steps:[
        'Проверь историю заказов в том же подтверждённом аккаунте, где оформлялась подписка.',
        'Если платёж ещё обрабатывается, не создавай новый счёт; дождись фактического статуса провайдера.',
        'Проверь уведомление на email и готовность подписки в личном кабинете. Счёт, открытая страница оплаты и оплаченный заказ — разные статусы.',
        'Если платёж подтверждён, но доступ не выдан, обратись в поддержку с номером заказа без банковских реквизитов и конфигурации.'
      ],
      link:'account'
    },
    switch:{
      label:'Проблема при смене Wi‑Fi / LTE',
      summary:'Смена сети может временно разорвать соединение. Настройки зависят от устройства и клиента.',
      steps:[
        'Убедись, что новый тип сети сам по себе предоставляет доступ к интернету.',
        'Проверь статус VPN-клиента: подключение могло остаться в состоянии ожидания после смены сети.',
        'Если клиент предлагает автоматическое переподключение, проверь его настройки и разрешения штатным способом.',
        'Если восстановить соединение не удаётся, ознакомься с инструкцией для устройства или отправь поддержке описание поведения.'
      ],
      link:'connect'
    }
  };
  const platformTips={
    android:'На Android используй системный диалог разрешения VPN и настройки совместимого клиента.',
    ios:'На iPhone и iPad проверь разрешение VPN в настройках и поддержку профиля в клиенте; правила управляемого iPad необходимо соблюдать.',
    windows:'В Windows проверь разрешение VPN-клиента и наличие обновлений приложения. Не отключай защитные механизмы системы для диагностики.',
    macos:'На Mac проверь системное разрешение VPN и совместимость версии macOS с приложением.',
    linux:'На Linux проверь поддержку нужного протокола официальным клиентом и доступность сети без VPN.'
  };

  let platform='android';
  let problem='connect';
  const selected=new Set();
  const title=root.querySelector('[data-ultra-title]');
  const summary=root.querySelector('[data-ultra-summary]');
  const steps=root.querySelector('[data-ultra-steps]');
  const counter=root.querySelector('[data-ultra-count]');
  const progress=root.querySelector('[data-ultra-progress]');
  const notice=root.querySelector('[data-ultra-copy-status]');
  const help=root.querySelector('[data-ultra-help]');
  const manual=root.querySelector('[data-ultra-manual]');
  const manualInput=root.querySelector('[data-ultra-manual-input]');
  const total=4;

  const build=(tag,css,text)=>{
    const node=document.createElement(tag);
    if(css)node.className=css;
    if(text!==undefined)node.textContent=String(text);
    return node;
  };
  function route(){
    const base=issues[problem].link;
    if(base==='connect')return 'connect.html?device='+encodeURIComponent(platform);
    if(base==='account')return 'https://vainahvpn-python-preview.onrender.com/account.html';
    return 'diagnostics.html';
  }
  function updateProgress(){
    counter.textContent=selected.size+' / '+total;
    progress.value=selected.size;
    progress.max=total;
    const finished=selected.size===total;
    notice.textContent=finished
      ?'Все шаги отмечены. Если проблема осталась, отправь описание в поддержку.'
      :'';
  }
  function view(){
    root.querySelectorAll('[data-ultra-platform]').forEach(button=>
      button.setAttribute('aria-pressed',String(button.dataset.ultraPlatform===platform))
    );
    root.querySelectorAll('[data-ultra-problem]').forEach(button=>
      button.setAttribute('aria-pressed',String(button.dataset.ultraProblem===problem))
    );
    const data=issues[problem];
    title.textContent=data.label;
    summary.textContent=data.summary+' '+platformTips[platform];
    help.href=route();
    help.textContent=problem==='account'||problem==='payment'
      ?'Открыть личный кабинет ↗'
      :problem==='slow'
        ?'Открыть полную диагностику ↗'
        :'Инструкция для '+names[platform]+' ↗';
    steps.replaceChildren();
    data.steps.forEach((description,index)=>{
      const li=build('li','vx-ultra-step');
      const label=build('label');
      const checkbox=build('input');
      checkbox.type='checkbox';
      checkbox.checked=selected.has(index);
      checkbox.setAttribute('aria-label','Шаг '+(index+1)+' — выполнен');
      const content=build('span','vx-ultra-step-content');
      content.append(
        build('small','vx-ultra-step-number',String(index+1).padStart(2,'0')),
        build('span','',description)
      );
      checkbox.addEventListener('change',()=>{
        if(checkbox.checked)selected.add(index);
        else selected.delete(index);
        updateProgress();
      });
      label.append(checkbox,content);
      li.append(label);
      steps.append(li);
    });
    manual.hidden=true;
    manualInput.value='';
    updateProgress();
  }

  root.querySelectorAll('[data-ultra-platform]').forEach(button=>{
    button.addEventListener('click',()=>{
      const next=button.dataset.ultraPlatform;
      if(!(next in names))return;
      platform=next;
      selected.clear();
      view();
    });
  });
  root.querySelectorAll('[data-ultra-problem]').forEach(button=>{
    button.addEventListener('click',()=>{
      const next=button.dataset.ultraProblem;
      if(!(next in issues))return;
      problem=next;
      selected.clear();
      view();
    });
  });
  root.querySelector('[data-ultra-reset]')?.addEventListener('click',()=>{
    selected.clear();
    view();
  });

  function supportSummary(){
    const data=issues[problem];
    const done=[...selected].sort((a,b)=>a-b).map(i=>i+1).join(', ')||'нет';
    return [
      'Обращение по Vainah VPN',
      'Устройство: '+names[platform],
      'Ситуация: '+data.label,
      'Выполненные шаги из '+total+': '+done,
      'Проблема после проверки: [опишите здесь, без VPN-ключа и личных данных]',
      'Текст ошибки (без секретных данных): [если есть]',
      'Создано локальным мастером Vainah Repair; состояние VPN не измерялось.'
    ].join('\n');
  }
  root.querySelector('[data-ultra-copy]')?.addEventListener('click',async()=>{
    const text=supportSummary();
    try{
      if(!navigator.clipboard?.writeText)throw Error('CLIPBOARD_UNAVAILABLE');
      await navigator.clipboard.writeText(text);
      manual.hidden=true;
      notice.textContent='Описание скопировано. Вставь его в обращение и добавь симптомы без секретных данных.';
    }catch{
      manual.hidden=false;
      manualInput.value=text;
      notice.textContent='Автоматическое копирование недоступно. Выдели текст ниже и скопируй вручную.';
      manualInput.focus();
      manualInput.select?.();
    }
  });
  view();
})();
