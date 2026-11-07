/* Server allowlist: 11 paid, 10 read-only previews, one trial. */
(() => {
  'use strict';
  const root=document.querySelector('[data-tariff-catalog]');
  const status=document.getElementById('tariff-catalog-status');
  if(!root||!status)return;
  const allowedPaid=new Set(['7','14','30','45','60','90','120','180','365','30-family','365-family']);
  const upcomingIds=new Set(['mini-3d','sprint-5d','start-plus-21d','balance-75d','comfort-150d','max-270d','legend-730d','family-plus-90d','family-pro-180d','family-max-730d']);
  const order=['trial-free','mini-3d','sprint-5d','7','14',
    'start-plus-21d','30','45','60','balance-75d','90','120',
    'comfort-150d','180','max-270d','365','legend-730d',
    '30-family','family-plus-90d','family-pro-180d',
    '365-family','family-max-730d'];
  const filters=Array.from(document.querySelectorAll?.('[data-tariff-filter]')||[]);
  let visibleCards=[];
  let currentFilter='all';
  function applyFilter(){
    let count=0;
    for(const card of visibleCards){
      card.hidden=currentFilter!=='all' && card.tariffSegment!==currentFilter;
      if(!card.hidden)count++;
    }
    for(const button of filters){
      button.setAttribute('aria-pressed',
        String(button.dataset.tariffFilter===currentFilter));
    }
    const counter=document.getElementById('tariff-filter-count');
    if(counter)counter.textContent=count+' из '+visibleCards.length+' платных тарифов';
  }
  for(const button of filters)button.addEventListener('click',()=>{
    const next=button.dataset.tariffFilter;
    if(['all','short','standard','long','family'].includes(next)){
      currentFilter=next;applyFilter();
    }
  });
  const create=(tag,text='',className='')=>{
    const result=document.createElement(tag);
    result.textContent=String(text);
    if(className)result.className=className;
    return result;
  };
  function valid(plan){
    return plan && typeof plan==='object' &&
      order.includes(plan.id) &&
      typeof plan.title==='string' &&
      plan.title.length>0 && plan.title.length<=60 &&
      Number.isInteger(plan.days) && plan.days>=1 && plan.days<=730 &&
      Number.isInteger(plan.devices) && plan.devices>=1 && plan.devices<=6 &&
      typeof plan.price_rub==='string' &&
      /^(0|[1-9][0-9]{0,5})\.[0-9]{2}$/.test(plan.price_rub) &&
      (plan.id==='trial-free'?
        (plan.status==='trial' && plan.price_rub==='0.00' &&
         plan.checkout_supported===false && plan.traffic_gb===10):
       allowedPaid.has(plan.id)?
        (plan.status==='existing' && plan.checkout_supported===true &&
         plan.checkout_path==='/checkout.html?plan='+plan.id):
        (upcomingIds.has(plan.id) && plan.status==='upcoming' &&
         plan.checkout_supported===false && plan.checkout_path===null));
  }
  function render(plans){
    const paid=plans.filter(plan=>plan.status!=='trial');
    const live=paid.filter(plan=>plan.status==='existing');
    const queued=paid.filter(plan=>plan.status==='upcoming');
    const fragment=document.createDocumentFragment();
    visibleCards=[];
    for(const plan of paid){
      const card=create('article','','plan tariff-card');
      card.tariffSegment=plan.segment;
      const eyebrow=create('div',plan.days+' ДНЕЙ','duration');
      card.append(eyebrow);
      const badge=create('span',
        plan.status==='upcoming'?'СКОРО':String(plan.tag||'ДОСТУПЕН'),
        'tariff-label');
      card.append(badge);
      card.append(create('h3',plan.title));
      const rub=create('div','','price');
      rub.append(create('span',Number(plan.price_rub).toLocaleString('ru-RU')+' ₽'));
      if(plan.days>=28){
        const monthly=Math.round((Number(plan.price_rub)*30/plan.days));
        rub.append(create('small',' ≈ '+monthly+' ₽ за 30 дней'));
      }
      card.append(rub);
      const notes=plan.devices+' '+(plan.devices===6?'устройств':'устройства');
      card.append(create('p',notes+' · VPN-доступ','plan-desc'));
      if(plan.status==='upcoming'){
        card.classList.add('tariff-upcoming');
        card.append(create('p',
          'Предложение в подготовке. Оплата и выдача пока не включены.',
          'tariff-note'));
        const disabled=create('button','В подготовке','btn btn-border');
        disabled.type='button';disabled.disabled=true;
        disabled.setAttribute('aria-label',
          'Тариф '+plan.title+' ещё не доступен для оплаты');
        card.append(disabled);
      } else if(plan.checkout_supported===true &&
        allowedPaid.has(plan.id) &&
        plan.checkout_path==='/checkout.html?plan='+plan.id){
        const link=create('a','Выбрать тариф ↗','btn btn-primary');
        link.href=plan.checkout_path;
        card.append(link);
      } else {
        // No unchecked URL can ever be followed as a payment link.
        card.append(create('p','Оформление недоступно.','tariff-note'));
      }
      visibleCards.push(card);
      fragment.append(card);
    }
    root.replaceChildren(fragment);
    applyFilter();
    status.textContent=
      '22 варианта: '+live.length+' действующих платных, '+queued.length+' в подготовке и 1 бесплатный пробный.';
    const counter=document.getElementById('tariff-compare-label');
    if(counter)counter.textContent=
      'Сравнить все 22 варианта ↗';
  }
  async function load(){
    status.textContent='Загружаем актуальный каталог тарифов…';
    try{
      const response=await fetch('/api/site/tariffs',{
        method:'GET',cache:'no-store',credentials:'omit',
        headers:{Accept:'application/json'}
      });
      if(!response.ok)throw Error('CATALOG_UNAVAILABLE');
      const data=await response.json();
      const plans=Array.isArray(data.plans)?data.plans:[];
      if(data.total!==22 || plans.length!==22 ||
        new Set(plans.map(p=>p.id)).size!==22 ||
        !plans.every(valid) ||
        plans.filter(p=>p.status==='trial').length!==1 ||
        plans.filter(p=>p.status==='existing').length!==11 ||
        plans.filter(p=>p.status==='upcoming').length!==10
      )throw Error('CATALOG_INVALID');
      render(plans);
    }catch{
      // Existing six verified static cards remain clickable if API is down.
      status.textContent='Новые тарифы пока не загрузились. Ниже показаны 6 действующих тарифов. Попробуй обновить страницу.';
    }
  }
  void load();
})();
