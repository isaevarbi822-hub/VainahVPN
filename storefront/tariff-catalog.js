/* Vainah VPN: 21 live paid plans, smart discovery + local plan comparison.
   The server owns all prices, eligibility, checkout and VPN fulfillment. */
(() => {
  'use strict';
  const root=document.querySelector('[data-tariff-catalog]');
  const status=document.getElementById('tariff-catalog-status');
  if(!root||!status)return;
  const paidIds=new Set([
    '7','14','30','45','60','90','120','180','365','30-family','365-family',
    'mini-3d','sprint-5d','start-plus-21d','balance-75d','comfort-150d',
    'max-270d','legend-730d','family-plus-90d','family-pro-180d','family-max-730d'
  ]);
  const order=[
    'trial-free','mini-3d','sprint-5d','7','14','start-plus-21d',
    '30','45','60','balance-75d','90','120','comfort-150d','180',
    'max-270d','365','legend-730d','30-family','family-plus-90d',
    'family-pro-180d','365-family','family-max-730d'
  ];
  const filters=Array.from(document.querySelectorAll?.('[data-tariff-filter]')||[]);
  const search=document.querySelector('[data-tariff-search]');
  const sort=document.querySelector('[data-tariff-sort]');
  const device=document.querySelector('[data-tariff-devices]');
  const clear=document.querySelector('[data-tariff-reset]');
  const count=document.getElementById('tariff-filter-count');
  const empty=document.querySelector('[data-tariff-empty]');
  const insight=document.querySelector('[data-tariff-insight]');
  const compareBox=document.querySelector('[data-tariff-compare]');
  const compareItems=document.querySelector('[data-tariff-compare-items]');
  const compareMessage=document.querySelector('[data-tariff-compare-message]');
  const compareClear=document.querySelector('[data-tariff-compare-clear]');
  let selectedFilter='all';
  let paid=[];
  let cards=[];
  const selected=new Set();
  const fmt=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0});
  const elem=(tag,text='',cls='')=>{
    const node=document.createElement(tag);
    node.textContent=String(text);
    if(cls)node.className=cls;
    return node;
  };
  const priceValue=plan=>Number(plan.price_rub);
  const daily=plan=>priceValue(plan)/plan.days;
  const money=amount=>fmt.format(amount)+' ₽';
  const moneyDaily=amount=>new Intl.NumberFormat('ru-RU',{
    minimumFractionDigits:2,maximumFractionDigits:2
  }).format(amount)+' ₽';
  const label=plan=>plan.devices===6?'семейный':'личный';
  function safe(plan){
    if(!plan||typeof plan!=='object'||!order.includes(plan.id)||
       typeof plan.title!=='string'||plan.title.length<1||plan.title.length>60||
       !Number.isInteger(plan.days)||plan.days<1||plan.days>730||
       !Number.isInteger(plan.devices)||![2,3,6].includes(plan.devices)||
       typeof plan.price_rub!=='string'||
       !/^(0|[1-9][0-9]{0,5})\.[0-9]{2}$/.test(plan.price_rub))return false;
    if(plan.id==='trial-free')
      return plan.status==='trial'&&plan.price_rub==='0.00'&&
        plan.traffic_gb===10&&plan.checkout_supported===false;
    return paidIds.has(plan.id)&&plan.status==='existing'&&
      plan.checkout_supported===true&&
      plan.checkout_path==='/checkout.html?plan='+plan.id&&
      ['short','standard','long','family'].includes(plan.segment);
  }
  function filtered(){
    const q=String(search?.value||'').toLocaleLowerCase('ru').trim();
    const terms=q.split(/\s+/).filter(Boolean).slice(0,7);
    const byDevices=device?.value||'all';
    const result=cards.filter(({plan})=>{
      if(selectedFilter!=='all'&&plan.segment!==selectedFilter)return false;
      if(byDevices==='3'&&plan.devices!==3)return false;
      if(byDevices==='6'&&plan.devices!==6)return false;
      const haystack=(plan.title+' '+plan.days+' дней '+plan.devices+
        ' устройств '+label(plan)+' '+plan.price_rub+' ₽').toLocaleLowerCase('ru');
      return terms.every(t=>haystack.includes(t));
    });
    const mode=sort?.value||'days';
    const comparer={
      days:(a,b)=>a.days-b.days||priceValue(a)-priceValue(b),
      price:(a,b)=>priceValue(a)-priceValue(b)||a.days-b.days,
      daily:(a,b)=>daily(a)-daily(b)||priceValue(a)-priceValue(b),
      longest:(a,b)=>b.days-a.days||priceValue(a)-priceValue(b)
    }[mode]||((a,b)=>a.days-b.days);
    result.sort((a,b)=>comparer(a.plan,b.plan));
    return result;
  }
  function show(){
    if(!cards.length)return;
    const matching=filtered();
    const shown=new Set(matching.map(c=>c.plan.id));
    const fragment=document.createDocumentFragment();
    // Reorder only DOM elements constructed from validated API data.
    for(const c of matching){c.card.hidden=false;fragment.append(c.card);}
    for(const c of cards){
      if(!shown.has(c.plan.id)){c.card.hidden=true;fragment.append(c.card);}
    }
    root.replaceChildren(fragment);
    for(const b of filters){
      b.setAttribute('aria-pressed',String(b.dataset.tariffFilter===selectedFilter));
    }
    if(count)count.textContent=matching.length+' из '+cards.length+' платных тарифов';
    if(empty)empty.hidden=matching.length!==0;
    if(insight){
      const cheapest=matching.slice().sort((a,b)=>priceValue(a.plan)-priceValue(b.plan))[0];
      const bestDaily=matching.slice().sort((a,b)=>daily(a.plan)-daily(b.plan))[0];
      insight.textContent=cheapest&&bestDaily?
        'Самый доступный в выборке: '+cheapest.plan.title+' · '+money(priceValue(cheapest.plan))+
        '. Минимальная цена за день: '+bestDaily.plan.title+' · ≈'+
        moneyDaily(daily(bestDaily.plan))+' за день'+
        '. Сравнение стоимости не означает сравнение скорости серверов.':
        'Ничего не найдено. Измени запрос или сбрось фильтры.';
    }
  }
  function updateCompare(){
    if(!compareBox||!compareItems)return;
    compareBox.hidden=selected.size===0;
    compareItems.replaceChildren();
    const chosen=paid.filter(p=>selected.has(p.id));
    for(const p of chosen){
      const card=elem('article','','tariff-compare-card');
      card.append(elem('strong',p.title));
      card.append(elem('span',money(priceValue(p))));
      card.append(elem('small',p.days+' дней · '+p.devices+
        ' устройства · ≈'+moneyDaily(daily(p))+'/день'));
      const link=elem('a','Оформить ↗','btn btn-primary');
      link.href='/checkout.html?plan='+p.id;
      card.append(link);
      const remove=elem('button','Убрать из сравнения','tariff-compare-remove');
      remove.type='button';
      remove.addEventListener?.('click',()=>{selected.delete(p.id);updateCompare();});
      card.append(remove);
      compareItems.append(card);
    }
    for(const {plan,compareButton} of cards){
      const active=selected.has(plan.id);
      compareButton.setAttribute('aria-pressed',String(active));
      compareButton.textContent=active?'✓ В сравнении':'Сравнить';
      compareButton.disabled=!active&&selected.size>=3;
    }
    if(compareMessage)compareMessage.textContent=
      'Выбрано '+chosen.length+' из 3. Сравнение локальное — заказ не создаётся.';
  }
  function render(plans){
    paid=plans.filter(p=>p.status==='existing');
    cards=[];
    const frag=document.createDocumentFragment();
    for(const p of paid){
      const card=elem('article','','plan tariff-card');
      card.append(elem('div',p.days+' ДНЕЙ','duration'));
      card.append(elem('span',String(p.tag||'ДОСТУПЕН'),'tariff-label'));
      card.append(elem('h3',p.title));
      const amount=elem('div','','price');
      amount.append(elem('span',money(priceValue(p))));
      amount.append(elem('small','≈'+moneyDaily(daily(p))+
        ' за день · ≈'+money(Math.round(priceValue(p)*30/p.days))+' за 30 дней'));
      card.append(amount);
      card.append(elem('p','До '+p.devices+' устройств · VPN-доступ','plan-desc'));
      const link=elem('a','Выбрать тариф ↗','btn btn-primary');
      link.href=p.checkout_path;
      card.append(link);
      const compareButton=elem('button','Сравнить','btn btn-border tariff-compare-toggle');
      compareButton.type='button';
      compareButton.setAttribute('aria-pressed','false');
      compareButton.addEventListener?.('click',()=>{
        if(selected.has(p.id))selected.delete(p.id);
        else if(selected.size<3)selected.add(p.id);
        updateCompare();
      });
      card.append(compareButton);
      cards.push({plan:p,card,compareButton});
      frag.append(card);
    }
    root.replaceChildren(frag);
    show();
    updateCompare();
    status.textContent='21 платный тариф с оформлением через RollyPay и один бесплатный пробный день.';
    const counter=document.getElementById('tariff-compare-label');
    if(counter)counter.textContent='Сравнить все 22 варианта ↗';
  }
  for(const b of filters)b.addEventListener('click',()=>{
    const next=b.dataset.tariffFilter;
    if(['all','short','standard','long','family'].includes(next)){
      selectedFilter=next;show();
    }
  });
  search?.addEventListener('input',show);
  sort?.addEventListener('change',show);
  device?.addEventListener('change',show);
  clear?.addEventListener('click',()=>{
    selectedFilter='all';if(search)search.value='';
    if(sort)sort.value='days';if(device)device.value='all';
    show();search?.focus?.();
  });
  compareClear?.addEventListener('click',()=>{selected.clear();updateCompare();});
  async function load(){
    status.textContent='Загружаем цены с сервера…';
    try{
      const response=await fetch('/api/site/tariffs',{
        method:'GET',cache:'no-store',credentials:'omit',
        headers:{Accept:'application/json'}
      });
      if(!response.ok)throw Error('CATALOG_UNAVAILABLE');
      const data=await response.json();
      const plans=Array.isArray(data.plans)?data.plans:[];
      if(data.total!==22||plans.length!==22||
        new Set(plans.map(p=>p.id)).size!==22||!plans.every(safe)||
        plans.filter(p=>p.status==='existing').length!==21||
        plans.filter(p=>p.status==='trial').length!==1
      )throw Error('CATALOG_INVALID');
      render(plans);
    }catch{
      status.textContent='Каталог недоступен. Ниже остаются 6 основных тарифов. '+
        'Актуальную сумму уточняй на странице оформления.';
      if(insight)insight.textContent='Поиск и сравнение доступны после обновления каталога.';
      if(compareBox)compareBox.hidden=true;
    }
  }
  void load();
})();
