/* Vainah Next / visual route finder. Public read-only catalog only.
   Never create invoices, fake prices, change accounts, or claim VPN connection. */
(() => {
  'use strict';
  const root=document.querySelector('[data-vx-next-journey]');
  if(!root)return;
  const status=root.querySelector('[data-vx-next-status]');
  const results=root.querySelector('[data-vx-next-results]');
  const guide=root.querySelector('[data-vx-next-guide]');
  const allPlans=root.querySelector('[data-vx-next-all]');
  const chooser={
    platform:'android',
    devices:3,
    days:30
  };
  let paid=null;
  const fmt=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0});
  const money=value=>fmt.format(value)+' ₽';
  const staticOrigin='https://vainahvpn.onrender.com';
  const backend='https://vainahvpn-python-preview.onrender.com';
  const apiOrigin=window.location.origin===staticOrigin?backend:'';
  const make=(tag,text,cls)=>{
    const element=document.createElement(tag);
    element.textContent=String(text);
    if(cls)element.className=cls;
    return element;
  };
  function safe(p){
    return p&&typeof p==='object'&&typeof p.id==='string'&&
      /^[a-z0-9-]{1,64}$/.test(p.id)&&p.status==='existing'&&
      p.checkout_supported===true&&p.checkout_path==='/checkout.html?plan='+p.id&&
      [3,6].includes(p.devices)&&Number.isInteger(p.days)&&
      p.days>=2&&p.days<=730&&typeof p.title==='string'&&
      p.title.length>0&&p.title.length<=60&&
      typeof p.price_rub==='string'&&/^[1-9][0-9]{0,5}\.[0-9]{2}$/.test(p.price_rub);
  }
  function updateButtons(){
    root.querySelectorAll('[data-vx-next-choice]').forEach(button=>{
      const key=button.dataset.vxNextChoice;
      const actual=key==='platform'?chooser.platform:String(chooser[key]);
      button.setAttribute('aria-pressed',String(button.dataset.value===actual));
    });
    const platformPath=new URL('connect.html',window.location.href);
    platformPath.searchParams.set('device',chooser.platform);
    if(guide)guide.href=platformPath.pathname+platformPath.search;
    if(allPlans){
      const target=new URL('plans.html',window.location.href);
      target.searchParams.set('devices',String(chooser.devices));
      target.searchParams.set('sort','days');
      allPlans.href=target.pathname+target.search;
    }
  }
  function recommendations(){
    if(!Array.isArray(paid))return [];
    const options=paid.filter(p=>p.devices===chooser.devices);
    const target=chooser.days;
    const closest=options.slice().sort((a,b)=>
      Math.abs(a.days-target)-Math.abs(b.days-target)||
      a.days-b.days||Number(a.price_rub)-Number(b.price_rub));
    // Keep choices relevant to the requested duration, not only the cheapest
    // global plan (which could have a drastically different term).
    const range=options.filter(p=>p.days>=Math.max(2,target*.65)&&
      p.days<=Math.min(730,target*1.6));
    const affordable=range.slice().sort((a,b)=>Number(a.price_rub)-Number(b.price_rub));
    const daily=range.slice().sort((a,b)=>
      Number(a.price_rub)/a.days-Number(b.price_rub)/b.days);
    const picks=[],seen=new Set();
    for(const plan of [closest[0],affordable[0],daily[0],...closest]){
      if(plan&&!seen.has(plan.id)){seen.add(plan.id);picks.push(plan);}
      if(picks.length===3)break;
    }
    return picks;
  }
  function render(){
    updateButtons();
    results.replaceChildren();
    if(!paid){
      status.textContent='Для подбора проверяем данные в серверном каталоге. Пока нет подтверждения, стоимость не показываем.';
      const link=make('a','Посмотреть все тарифы ↗','vx-next-fallback');
      link.href=allPlans?.getAttribute('href')||'plans.html';
      results.append(link);
      return;
    }
    const picks=recommendations();
    if(!picks.length){
      status.textContent='Для выбранных условий подходящих тарифов в проверенном каталоге нет.';
      return;
    }
    status.textContent='Найдено '+picks.length+' варианта из действующего каталога. Это подбор по сроку, а не проверка скорости VPN или одобрение платежа.';
    for(let i=0;i<picks.length;i++){
      const plan=picks[i];
      const card=make('article','','vx-next-offer');
      const caption=make('span',i===0?'БЛИЖЕ К СРОКУ':i===1?'АЛЬТЕРНАТИВА':'ЕЩЁ ВАРИАНТ','vx-next-offer-tag');
      const title=make('h3',plan.title);
      const details=make('p',plan.days+' дней · до '+plan.devices+' устройств');
      const price=make('strong',money(Number(plan.price_rub)),'vx-next-price');
      const perDay=make('small','≈ '+new Intl.NumberFormat('ru-RU',{
        minimumFractionDigits:2,maximumFractionDigits:2
      }).format(Number(plan.price_rub)/plan.days)+' ₽ за день');
      const link=make('a','Выбрать подписку ↗','vx-next-offer-link');
      link.href=plan.checkout_path;
      card.append(caption,title,details,price,perDay,link);
      results.append(card);
    }
  }
  root.querySelectorAll('[data-vx-next-choice]').forEach(button=>{
    button.addEventListener('click',()=>{
      const key=button.dataset.vxNextChoice;
      const value=button.dataset.value;
      if(key==='platform'&&['android','ios','windows','macos','linux'].includes(value))
        chooser.platform=value;
      if(key==='devices'&&['3','6'].includes(value))chooser.devices=Number(value);
      if(key==='days'&&['7','30','365'].includes(value))chooser.days=Number(value);
      render();
    });
  });
  updateButtons();
  render();
  async function load(){
    try{
      const controller=new AbortController();
      const timeout=window.setTimeout(()=>controller.abort(),12000);
      let response;
      try{
        response=await fetch(apiOrigin+'/api/site/tariffs',{
          method:'GET',cache:'no-store',credentials:'omit',
          headers:{Accept:'application/json'},signal:controller.signal
        });
      }finally{window.clearTimeout(timeout);}
      if(!response.ok)throw Error('CATALOG_UNAVAILABLE');
      const data=await response.json();
      if(data.total!==76||!Array.isArray(data.plans)||data.plans.length!==76||
         new Set(data.plans.map(p=>p?.id)).size!==76)throw Error('CATALOG_INVALID');
      const confirmed=data.plans.filter(p=>p.status==='existing');
      if(confirmed.length!==75||!confirmed.every(safe)||
         data.plans.filter(p=>p.status==='trial').length!==1)
        throw Error('CATALOG_INVALID');
      paid=confirmed;
      render();
    }catch{
      paid=null;
      render();
      status.textContent='Не удалось проверить цены на сервере. Открой каталог или проверь доступность оплаты в кабинете; здесь нет выдуманных сумм.';
    }
  }
  void load();
})();
