/* Vainah VPN interactive toolkit: tariff advisor, setup guide and knowledge search.
   No credentials, no external requests and no fabricated prices. */
(() => {
  'use strict';
  const one=(q,root=document)=>root.querySelector(q);
  const many=(q,root=document)=>[...root.querySelectorAll(q)];
  const set=(node,value)=>{if(node)node.textContent=String(value)};
  const normal=value=>String(value||'').toLocaleLowerCase('ru').replace(/ё/g,'е').trim();

  function library(){
    const root=one('[data-knowledge-library]');
    if(!root)return;
    const query=one('[data-library-search]',root);
    const category=one('[data-library-category]',root);
    const cards=many('[data-library-card]',root);
    const count=one('[data-library-count]',root);
    const empty=one('[data-library-empty]',root);
    function update(){
      const term=normal(query?.value),group=category?.value||'all';
      let shown=0;
      for(const card of cards){
        const matched=(!term||normal(card.textContent).includes(term))&&
          (group==='all'||card.dataset.category===group);
        card.hidden=!matched;
        if(matched)shown++;
      }
      set(count,'Найдено: '+shown+' из '+cards.length+' материалов');
      if(empty)empty.hidden=shown!==0;
    }
    query?.addEventListener('input',update);
    category?.addEventListener('change',update);
    update();
  }

  function advisor(){
    const root=one('[data-tariff-advisor]');
    if(!root)return;
    const days=one('[data-wanted-days]',root);
    const devices=one('[data-wanted-devices]',root);
    const pending=one('[data-show-upcoming]',root);
    const dayLabel=one('[data-wanted-days-label]',root);
    const info=one('[data-advisor-info]',root);
    const output=one('[data-advisor-output]',root);
    const name=one('[data-advisor-name]',root);
    const price=one('[data-advisor-price]',root);
    const explanation=one('[data-advisor-explanation]',root);
    const payment=one('[data-advisor-payment]',root);
    const link=one('[data-advisor-link]',root);
    const paidIds=new Set(['30','60','90','180','365','365-family']);
    const futureIds=new Set(['7','14','45','120','30-family']);
    const catalogIds=new Set(['trial-free',...paidIds,...futureIds]);
    let catalogue=null;
    const currency=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2});
    function render(){
      const wantedDays=Math.max(7,Math.min(365,Number(days?.value)||30));
      const wantedDevices=Math.max(1,Math.min(6,Number(devices?.value)||3));
      const allowUpcoming=pending?.checked===true;
      set(dayLabel,wantedDays+' дн.');
      if(!catalogue)return;
      const options=catalogue.filter(p=>p.status==='existing'||
        (allowUpcoming&&p.status==='upcoming'));
      const matching=options.filter(p=>p.days>=wantedDays&&p.devices>=wantedDevices);
      matching.sort((a,b)=>a.kopeks-b.kopeks||a.days-b.days);
      const picked=matching[0];
      if(!picked){
        if(output)output.hidden=true;
        set(info,'Подходящего тарифа в выбранной категории сейчас нет. Попробуй изменить срок или число устройств.');
        return;
      }
      const isFuture=picked.status==='upcoming';
      set(name,picked.title+(isFuture?' · СКОРО':''));
      set(price,currency.format(picked.kopeks/100)+' ₽');
      set(explanation,picked.days+' дней · до '+picked.devices+
        ' устройств · полная стоимость подписки.');
      set(payment,isFuture?
        'Предварительная стоимость. Оплата и выдача через H1Cloud не проверены; этот тариф пока недоступен к покупке.':
        'Рекомендация из действующих планов. Выбранный тариф и доступность оплаты будут проверены при оформлении.');
      if(link){
        link.href=isFuture?'plans.html':'checkout.html?plan='+picked.id;
        set(link,isFuture?'Посмотреть будущий тариф ↗':'Оформить действующий тариф ↗');
      }
      set(info,isFuture?
        'Предварительный подбор из 11 платных предложений, 5 новых ещё не продаются.':
        'Самый дешёвый один подходящий действующий тариф из 6 проверенных вариантов.');
      if(output)output.hidden=false;
    }
    days?.addEventListener('input',render);
    devices?.addEventListener('change',render);
    pending?.addEventListener('change',render);
    for(const button of many('[data-days-preset]',root))
      button.addEventListener('click',()=>{
        if(days)days.value=button.dataset.daysPreset;
        render();
      });
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),9000);
    fetch('/api/site/tariffs',{
      method:'GET',cache:'no-store',credentials:'omit',
      headers:{Accept:'application/json'},signal:controller.signal
    }).then(async response=>{
      if(!response.ok)throw Error('API '+response.status);
      const data=await response.json();
      if(data.total!==12||!Array.isArray(data.plans)||data.plans.length!==12)
        throw Error('INVALID_CATALOG');
      const valid=data.plans.every(p=>
        p&&catalogIds.has(p.id)&&typeof p.title==='string'&&p.title.length<=60&&
        Number.isInteger(p.days)&&p.days>=1&&p.days<=365&&
        Number.isInteger(p.devices)&&p.devices>=2&&p.devices<=6&&
        typeof p.price_rub==='string'&&
        /^(0|[1-9][0-9]{0,5})\.[0-9]{2}$/.test(p.price_rub)&&
        (p.status==='trial'?p.id==='trial-free'&&p.price_rub==='0.00':
        p.status==='existing'?paidIds.has(p.id)&&p.checkout_supported===true&&
          p.checkout_path==='/checkout.html?plan='+p.id:
        p.status==='upcoming'&&futureIds.has(p.id)&&p.checkout_supported===false&&
          p.checkout_path===null)
      );
      if(!valid||new Set(data.plans.map(p=>p.id)).size!==12||
        data.plans.filter(p=>p.status==='existing').length!==6||
        data.plans.filter(p=>p.status==='upcoming').length!==5||
        data.plans.filter(p=>p.status==='trial').length!==1
      )throw Error('INVALID_CATALOG');
      catalogue=data.plans.filter(p=>p.status!=='trial').map(p=>({
        id:p.id,title:p.title,days:p.days,devices:p.devices,
        status:p.status,kopeks:Math.round(Number(p.price_rub)*100)
      }));
      render();
    }).catch(()=>{
      if(output)output.hidden=true;
      set(info,'Не удалось загрузить актуальные тарифы. Посмотри цены на странице «Тарифы» и попробуй позднее.');
    }).finally(()=>clearTimeout(timer));
  }

  function setup(){
    const root=one('[data-setup-wizard]');
    if(!root)return;
    const platformButtons=many('[data-platform-choice]',root);
    const stageButtons=many('[data-stage-choice]',root);
    const items=many('[data-setup-check]',root);
    const bar=one('[data-setup-progress]',root);
    const progress=one('.tool-progress',root);
    const count=one('[data-setup-complete]',root);
    const reset=one('[data-setup-reset]',root);
    let platform='ios',stage='before';
    const titles={ios:'iPhone / iPad',android:'Android',windows:'Windows',macos:'macOS'};
    const instructions={
      before:{
        title:'Начни с оформления',
        summary:'Для '+titles.ios+' и других устройств порядок покупки одинаковый.',
        steps:[
          'Выбери тариф по сроку и числу устройств либо открой пробный период.',
          'Войди в личный кабинет с подтверждённым email.',
          'После подтверждённой оплаты открой выданную VPN-ссылку только в совместимом VPN-клиенте.'
        ],
        href:'plans.html',link:'Выбрать тариф ↗'
      },
      link:{
        title:'Настрой VPN-клиент',
        steps:[
          'Установи совместимый VPN-клиент из официального магазина или доверенного источника.',
          'Скопируй личную ссылку в кабинете; не публикуй её и не отправляй в поддержку.',
          'Импортируй подписку внутри клиента и проверь соединение.',
          'Если ссылка не принимается, открой мастер решения проблем.'
        ],href:'guide.html',link:'Инструкция по подключению ↗'
      },
      issue:{
        title:'Найдём причину ошибки',
        steps:[
          'Сначала проверь, работает ли обычный интернет без VPN.',
          'Обнови данные в кабинете и проверь срок и состояние H1Cloud.',
          'Перезапусти совместимый клиент и повтори импорт ссылки.',
          'Если проблема сохраняется, используй диагностику и обратись в поддержку без передачи VPN-ключа.'
        ],href:'repair-wizard.html',link:'Мастер решения проблем ↗'
      }
    };
    const key=()=>('vainah-setup-session-v2-'+platform);
    function load(){
      let stored=null;
      try{stored=JSON.parse(sessionStorage.getItem(key())||'null')}catch{}
      items.forEach((item,index)=>{item.checked=Array.isArray(stored)&&stored[index]===true;});
      updateProgress();
    }
    function updateProgress(){
      const done=items.filter(item=>item.checked).length;
      if(bar)bar.style.width=(items.length?done/items.length*100:0)+'%';
      progress?.setAttribute('aria-valuenow',String(done));
      set(count,done+' из '+items.length+' шагов отмечено · '+titles[platform]);
      try{sessionStorage.setItem(key(),JSON.stringify(items.map(item=>item.checked)))}catch{}
    }
    function render(){
      for(const button of platformButtons)button.setAttribute('aria-pressed',String(button.dataset.platformChoice===platform));
      for(const button of stageButtons)button.setAttribute('aria-pressed',String(button.dataset.stageChoice===stage));
      const guide=instructions[stage],name=titles[platform];
      set(one('[data-wizard-title]',root),guide.title+' · '+name);
      set(one('[data-wizard-summary]',root),
        stage==='before'?'Для '+name+' сначала нужен оплаченный или пробный доступ.':
        stage==='link'?'Действия для '+name+' могут зависеть от установленного приложения.':
        'Ошибки на '+name+' иногда связаны с сетью, а не с VPN-профилем.');
      const list=one('[data-wizard-steps]',root);
      if(list){
        list.replaceChildren();
        for(const step of guide.steps){const li=document.createElement('li');li.textContent=step;list.append(li);}
      }
      const a=one('[data-wizard-link]',root);
      if(a){a.href=guide.href;set(a,guide.link);}
    }
    for(const button of platformButtons)button.addEventListener('click',()=>{
      const next=button.dataset.platformChoice;
      if(!Object.hasOwn(titles,next))return;
      platform=next;render();load();
    });
    for(const button of stageButtons)button.addEventListener('click',()=>{
      const next=button.dataset.stageChoice;
      if(!Object.hasOwn(instructions,next))return;
      stage=next;render();
    });
    for(const item of items)item.addEventListener('change',updateProgress);
    reset?.addEventListener('click',()=>{
      items.forEach(item=>item.checked=false);
      updateProgress();
    });
    render();load();
  }
  advisor();setup();library();
})();