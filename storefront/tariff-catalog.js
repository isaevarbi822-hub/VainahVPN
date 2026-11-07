/* A 12-option public showcase; live checkout stays on verified legacy plans. */
(() => {
  'use strict';
  const root=document.querySelector('[data-tariff-catalog]');
  const status=document.getElementById('tariff-catalog-status');
  if(!root||!status)return;
  const allowedPaid=new Set(['30','60','90','180','365','365-family']);
  const order=[
    'trial-free','7','14','30','45','60','90','120',
    '180','365','30-family','365-family'
  ];
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
      Number.isInteger(plan.days) && plan.days>=1 && plan.days<=366 &&
      Number.isInteger(plan.devices) && plan.devices>=1 && plan.devices<=6 &&
      typeof plan.price_rub==='string' &&
      /^(0|[1-9][0-9]{0,5})\.[0-9]{2}$/.test(plan.price_rub) &&
      ['existing','upcoming','trial'].includes(plan.status);
  }
  function render(plans){
    const paid=plans.filter(plan=>plan.status!=='trial');
    const live=paid.filter(plan=>plan.status==='existing');
    const queued=paid.filter(plan=>plan.status==='upcoming');
    const fragment=document.createDocumentFragment();
    for(const plan of paid){
      const card=create('article','','plan tariff-card');
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
      fragment.append(card);
    }
    root.replaceChildren(fragment);
    status.textContent=
      '12 вариантов: '+live.length+' действующих платных, '+
      queued.length+' новых в подготовке и 1 бесплатный пробный.';
    const counter=document.getElementById('tariff-compare-label');
    if(counter)counter.textContent=
      'Сравнить 6 действующих платных тарифов ↗';
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
      if(data.total!==12 || plans.length!==12 ||
        new Set(plans.map(p=>p.id)).size!==12 ||
        !plans.every(valid) ||
        plans.filter(p=>p.status==='trial').length!==1 ||
        plans.filter(p=>p.status==='existing').length!==6 ||
        plans.filter(p=>p.status==='upcoming').length!==5
      )throw Error('CATALOG_INVALID');
      render(plans);
    }catch{
      // Existing six verified static cards remain clickable if API is down.
      status.textContent='Новые тарифы пока не загрузились. Ниже показаны 6 действующих тарифов. Попробуй обновить страницу.';
    }
  }
  void load();
})();
