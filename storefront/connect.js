/* Vainah Connect: device-specific local checklist, no credentials or storage. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const container=$('vc-steps'),tabs=[...document.querySelectorAll('[data-vc-platform]')];
  if(!container||!tabs.length)return;
  const flows={
    android:{name:'Android',note:'Понадобится совместимый клиент VLESS/Reality и разрешение Android на VPN-подключение.',steps:[
      'Войди в личный кабинет Vainah VPN с подтверждённым аккаунтом.',
      'Получить VPN-ссылку или показать личный QR-код, если подписка оплачена и активна.',
      'Импортируй ссылку или QR-код в совместимый VPN-клиент на Android.',
      'Разреши системное VPN-подключение, включи VPN и проверь работу сети в клиенте.'
    ]},
    ios:{name:'iPhone / iPad',note:'Нужен совместимый с VLESS/Reality VPN-клиент для iOS или iPadOS.',steps:[
      'Открой личный кабинет Vainah VPN в Safari и войди в аккаунт.',
      'Получи личную VPN-ссылку или QR-код только после подтверждённой покупки.',
      'Импортируй конфигурацию в совместимый клиент iOS/iPadOS.',
      'Подтверди системный запрос на установку VPN и проверь подключение в клиенте.'
    ]},
    windows:{name:'Windows',note:'Используй клиент, поддерживающий VLESS/Reality и нужный формат подписки.',steps:[
      'Войди в личный кабинет на своём компьютере с Windows.',
      'Скопируй персональную VPN-ссылку после проверки подписки.',
      'Импортируй ссылку в поддерживаемый клиент; если импорт не работает, проверь формат и сообщение об ошибке.',
      'Включи системный туннель в клиенте, если он требуется, и проверь доступность сети.'
    ]},
    macos:{name:'macOS',note:'Потребуется совместимое приложение с поддержкой системного VPN-профиля.',steps:[
      'Войди в свой аккаунт Vainah VPN на Mac.',
      'Скопируй персональную ссылку или покажи QR для совместимого клиента.',
      'Импортируй конфигурацию в выбранное VPN-приложение macOS.',
      'Разреши добавление VPN-профиля в системных настройках и проверь работу сети.'
    ]},
    linux:{name:'Linux',note:'Нативное приложение Vainah VPN для Linux не заявлено; понадобится сторонний совместимый клиент.',steps:[
      'Войди в личный кабинет Vainah VPN через браузер Linux.',
      'Скопируй личную VPN-ссылку из подтверждённой подписки.',
      'Выбери проверенный клиент Linux с поддержкой VLESS/Reality и импортируй конфигурацию.',
      'Разреши настройку сетевого интерфейса по инструкции клиента и проверь соединение.'
    ]}
  };
  let current='android',done=new Set();
  const info=$('vc-selected-note'),heading=$('vc-selected-title');
  const bar=$('vc-progress'),fill=$('vc-progress-fill'),count=$('vc-progress-text');
  const copy=$('vc-copy'),reset=$('vc-reset'),status=$('vc-action-status'),manual=$('vc-manual');
  function update(){
    const total=flows[current].steps.length;
    count.textContent=done.size+' из '+total+' шагов отмечено';
    bar.setAttribute('aria-valuenow',String(done.size));
    bar.setAttribute('aria-valuemax',String(total));
    fill.style.width=Math.round(done.size/total*100)+'%';
  }
  function render(){
    const flow=flows[current];
    heading.textContent='2. Подготовь подключение на '+flow.name;
    info.textContent=flow.note;
    tabs.forEach(button=>{
      const selected=button.dataset.vcPlatform===current;
      button.setAttribute('aria-selected',String(selected));
      button.tabIndex=selected?0:-1;
    });
    container.replaceChildren();
    flow.steps.forEach((description,index)=>{
      const label=document.createElement('label');label.className='vc-step';
      const checkbox=document.createElement('input');checkbox.type='checkbox';
      checkbox.checked=done.has(index);
      checkbox.addEventListener('change',()=>{
        if(checkbox.checked)done.add(index);else done.delete(index);
        update();
      });
      const text=document.createElement('span');
      text.textContent=(index+1)+'. '+description;
      label.append(checkbox,text);container.append(label);
    });
    update();
  }
  tabs.forEach(button=>button.addEventListener('click',()=>{
    current=button.dataset.vcPlatform;
    done=new Set();
    manual.hidden=true;
    status.textContent='Отметки хранятся только на открытой странице и не передаются на сервер.';
    render();
  }));
  reset.addEventListener('click',()=>{
    done.clear();manual.hidden=true;render();
  });
  copy.addEventListener('click',async()=>{
    const flow=flows[current];
    const plain=['Vainah Connect — '+flow.name,flow.note,...flow.steps.map((step,i)=>(i+1)+'. '+step)].join('\n');
    try{
      if(!navigator.clipboard?.writeText)throw Error('Clipboard unavailable');
      await navigator.clipboard.writeText(plain);
      status.textContent='Инструкция скопирована без ключей и персональных данных.';
    }catch{
      manual.hidden=false;manual.value=plain;manual.focus();manual.select();
      status.textContent='Копирование запрещено браузером. Выдели текст вручную.';
    }
  });
  render();
})();