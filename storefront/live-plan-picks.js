/* Vainah VPN / server-verified featured offers — never fabricates prices.
   Only public GET requests; no payment, auth or H1Cloud writes. */
(() => {
  'use strict';
  const root=document.querySelector('[data-live-plan-picks]');
  const message=document.querySelector('[data-live-plan-message]');
  const refresh=document.querySelector('[data-live-plan-refresh]');
  if(!root||!message)return;
  const ids=['pulse-2d','mini-3d','30','90','family-plus-90d','legend-730d'];
  const staticSite=location.origin==='https://vainahvpn.onrender.com';
  const publicApi=staticSite?'https://vainahvpn-python-preview.onrender.com':'';
  const checkoutMessage=document.querySelector('[data-checkout-message]');
  if(checkoutMessage)checkoutMessage.textContent=
    'Статус RollyPay проверяется на странице оформления. До подтверждения заказа деньги не списываются.';
  const escape=(tag,value,cls='')=>{
    const node=document.createElement(tag);node.textContent=String(value);
    if(cls)node.className=cls;return node;
  };
  const rub=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0});
  let generation=0;
  async function load(){
    const turn=++generation;
    if(refresh)refresh.disabled=true;
    message.textContent='Проверяем тарифы в реальном серверном каталоге…';
    try{
      const controller=new AbortController();
      const timer=setTimeout(()=>controller.abort(),18000);
      let response;
      try{
        response=await fetch(publicApi+'/api/site/tariffs',{
          method:'GET',cache:'no-store',credentials:'omit',redirect:'error',
          headers:{Accept:'application/json'},signal:controller.signal
        });
      }finally{clearTimeout(timer);}
      if(!response.ok)throw Error('UNAVAILABLE');
      const result=await response.json();
      if(result.total!==76||!Array.isArray(result.plans)||result.plans.length!==76)
        throw Error('CATALOG_MISMATCH');
      const byId=new Map(result.plans.map(p=>[p?.id,p]));
      if(byId.size!==76)throw Error('ID_MISMATCH');
      const picks=ids.map(id=>{
        const plan=byId.get(id);
        if(!plan||plan.id!==id||plan.status!=='existing'||
           plan.checkout_supported!==true||
           plan.checkout_path!=='/checkout.html?plan='+id||
           !Number.isInteger(plan.days)||plan.days<1||plan.days>730||
           ![3,6].includes(plan.devices)||
           typeof plan.title!=='string'||plan.title.length<1||plan.title.length>60||
           typeof plan.price_rub!=='string'||
           !/^[1-9][0-9]{0,5}\.[0-9]{2}$/.test(plan.price_rub)
        )throw Error('CATALOG_INVALID');
        return plan;
      });
      if(turn!==generation)return;
      const fragment=document.createDocumentFragment();
      for(const plan of picks){
        const card=escape('article','','vx-pick');
        const top=escape('div',plan.devices===6?'СЕМЕЙНЫЙ':'ЛИЧНЫЙ','vx-pick-label');
        const title=escape('h3',plan.title);
        const price=escape('strong',rub.format(Number(plan.price_rub))+' ₽','vx-pick-price');
        const subtitle=escape('p',plan.days+' дней · до '+plan.devices+' устройств',
          'vx-pick-details');
        const btn=escape('a','Выбрать тариф ↗','vx-pick-link');
        btn.href=plan.checkout_path;
        card.append(top,title,price,subtitle,btn);
        fragment.append(card);
      }
      root.replaceChildren(fragment);
      message.textContent='Цены получены из сервера. Выбор тарифа не списывает деньги; готовность RollyPay проверяется при оформлении.';
    }catch{
      if(turn===generation){
        const fallback=document.createElement('article');
        fallback.className='vx-pick';
        const title=escape('h3','Уточнить актуальные тарифы');
        const details=escape('p',
          'Серверный каталог временно недоступен. Цена и готовность оплаты уточняются при оформлении.',
          'vx-pick-details');
        const link=escape('a','Открыть страницу тарифов ↗','vx-pick-link');
        link.href='plans.html';
        fallback.append(title,details,link);
        root.replaceChildren(fallback);
        message.textContent='Проверка цен сейчас недоступна. На этой странице цены не подменяются приблизительными.';
      }
    }finally{if(turn===generation&&refresh)refresh.disabled=false;}
  }
  refresh?.addEventListener('click',()=>{void load();});
  void load();
})();