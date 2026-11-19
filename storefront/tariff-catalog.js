/* Vainah VPN: server catalog, filters and local plan comparison.
   The server owns all prices, eligibility, checkout and VPN fulfillment. */
(() => {
  'use strict';
  // The public CDN is a static site. Its catalog lives on the read-only Python API.
  // That endpoint explicitly allows this origin; checkout config and payment
  // requests MUST remain same-origin on the backend.
  const staticOrigin='https://vainahvpn.onrender.com';
  const apiOrigin=typeof window!=='undefined'&&window.location.origin===staticOrigin
    ?'https://vainahvpn-python-preview.onrender.com':'';
  const root=document.querySelector('[data-tariff-catalog]');
  const status=document.getElementById('tariff-catalog-status');
  if(!root||!status)return;
  const filters=Array.from(document.querySelectorAll?.('[data-tariff-filter]')||[]);
  const search=document.querySelector('[data-tariff-search]');
  const sort=document.querySelector('[data-tariff-sort]');
  const device=document.querySelector('[data-tariff-devices]');
  const clear=document.querySelector('[data-tariff-reset]');
  const budget=document.querySelector('[data-tariff-budget]');
  const more=document.querySelector('[data-tariff-more]');
  const checkoutReadiness=document.querySelector('[data-checkout-readiness]');
  const count=document.getElementById('tariff-filter-count');
  const empty=document.querySelector('[data-tariff-empty]');
  const insight=document.querySelector('[data-tariff-insight]');
  const compareBox=document.querySelector('[data-tariff-compare]');
  const compareItems=document.querySelector('[data-tariff-compare-items]');
  const compareMessage=document.querySelector('[data-tariff-compare-message]');
  const compareClear=document.querySelector('[data-tariff-compare-clear]');
  const favoritesOnlyButton=document.querySelector('[data-tariff-favorites-only]');
  const favoriteCount=document.querySelector('[data-tariff-favorite-count]');
  const shareButton=document.querySelector('[data-tariff-share]');
  const retryButton=document.querySelector('[data-tariff-retry]');
  const feedback=document.querySelector('[data-tariff-feedback]');
  let selectedFilter='all';
  // Allow the homepage's guided flow to open a pre-filtered *public* catalog.
  // URL params never choose a plan for purchase or set prices.
  const initial=new URLSearchParams(typeof window!=='undefined'?window.location.search:'');
  if(device&&['3','6'].includes(initial.get('devices')))
    device.value=initial.get('devices');
  if(sort&&['days','price','daily','longest'].includes(initial.get('sort')))
    sort.value=initial.get('sort');
  if(budget&&['100','250','500','1000','2000'].includes(initial.get('budget')))
    budget.value=initial.get('budget');
  if(['all','short','standard','long','family'].includes(initial.get('segment')))
    selectedFilter=initial.get('segment');
  let displayLimit=12;
  let paid=[];
  let cards=[];
  let favoritesOnly=false;
  const selected=new Set();
  const publicFavoriteKey='vainah-public-plan-favorites-v1';
  const favorites=new Set();
  const validId=id=>typeof id==='string'&&/^[a-z0-9-]{1,60}$/.test(id);
  const initialCompare=String(initial.get('compare')||'').split(',').slice(0,3);
  const storage=()=>{
    try{return typeof window!=='undefined'?window.localStorage:null;}
    catch{return null;}
  };
  try{
    const values=JSON.parse(storage()?.getItem(publicFavoriteKey)||'[]');
    if(Array.isArray(values))for(const id of values.slice(0,8)){
      if(validId(id)&&id!=='trial-free')favorites.add(id);
    }
  }catch{/* Private browsing blocks storage: favorites still work for this page. */}
  if(search&&initial.get('q'))search.value=String(initial.get('q')).slice(0,80);
  const fmt=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2});
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
    if(!plan||typeof plan!=='object'||!validId(plan.id)||
       typeof plan.title!=='string'||plan.title.length<1||plan.title.length>60||
       !Number.isInteger(plan.days)||plan.days<1||plan.days>730||
       !Number.isInteger(plan.devices)||![2,3,6].includes(plan.devices)||
       typeof plan.price_rub!=='string'||
       !/^(0|[1-9][0-9]{0,5})\.[0-9]{2}$/.test(plan.price_rub))return false;
    if(plan.id==='trial-free')
      return plan.status==='trial'&&plan.price_rub==='0.00'&&
        plan.traffic_gb===10&&plan.checkout_supported===false;
    return plan.status==='existing'&&priceValue(plan)>0&&[3,6].includes(plan.devices)&&
      plan.checkout_supported===true&&
      plan.checkout_path==='/checkout.html?plan='+plan.id&&
      ['short','standard','long','family'].includes(plan.segment);
  }
  function filtered(){
    const q=String(search?.value||'').toLocaleLowerCase('ru').trim();
    const terms=q.split(/\s+/).filter(Boolean).slice(0,7);
    const byDevices=device?.value||'all';
    const maxBudget=Number(budget?.value)||Infinity;
    const result=cards.filter(({plan})=>{
      if(selectedFilter!=='all'&&plan.segment!==selectedFilter)return false;
      if(favoritesOnly&&!favorites.has(plan.id))return false;
      if(byDevices==='3'&&plan.devices!==3)return false;
      if(byDevices==='6'&&plan.devices!==6)return false;
      if(priceValue(plan)>maxBudget)return false;
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
    const visibleIds=new Set(matching.slice(0,displayLimit).map(c=>c.plan.id));
    const fragment=document.createDocumentFragment();
    // Reorder only DOM elements constructed from validated API data.
    for(const c of matching){c.card.hidden=!visibleIds.has(c.plan.id);fragment.append(c.card);}
    for(const c of cards){
      if(!shown.has(c.plan.id)){c.card.hidden=true;fragment.append(c.card);}
    }
    root.replaceChildren(fragment);
    for(const b of filters){
      b.setAttribute('aria-pressed',String(b.dataset.tariffFilter===selectedFilter));
    }
    if(count)count.textContent='Найдено '+matching.length+' из '+cards.length+
      ' · показано '+Math.min(displayLimit,matching.length)+
      (favoritesOnly?' · только избранное':''); 
    if(more){more.hidden=matching.length<=displayLimit;
      more.textContent='Показать ещё '+Math.min(12,matching.length-displayLimit)+' тарифов ↓';}
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
  function updateFavorites(){
    if(favoriteCount)favoriteCount.textContent=String(favorites.size);
    if(favoritesOnlyButton)favoritesOnlyButton.setAttribute('aria-pressed',String(favoritesOnly));
    for(const {plan,favoriteButton} of cards){
      const active=favorites.has(plan.id);
      if(!favoriteButton)continue;
      favoriteButton.setAttribute('aria-pressed',String(active));
      favoriteButton.textContent=active?'★ Сохранён':'☆ В избранное';
      favoriteButton.setAttribute('aria-label',
        active?'Убрать '+plan.title+' из избранного':'Сохранить '+plan.title+' в избранном');
    }
  }
  function persistFavorites(){
    try{storage()?.setItem(publicFavoriteKey,JSON.stringify([...favorites]));}
    catch{/* Safari private mode: in-memory favorites still work. */}
  }
  function toggleFavorite(plan){
    if(favorites.has(plan.id))favorites.delete(plan.id);
    else if(favorites.size<8)favorites.add(plan.id);
    else{
      if(feedback)feedback.textContent='Можно сохранить не больше 8 тарифов. Убери один из избранного.';
      return;
    }
    persistFavorites();
    updateFavorites();
    if(favoritesOnly)show();
    if(feedback)feedback.textContent=favorites.has(plan.id)
      ?'Тариф сохранён в этом браузере.':'Тариф убран из избранного.';
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
      link.href=apiOrigin+p.checkout_path;
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
    for(const id of favorites)if(!paid.some(plan=>plan.id===id))favorites.delete(id);
    for(const id of selected)if(!paid.some(plan=>plan.id===id))selected.delete(id);
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
      link.href=apiOrigin+p.checkout_path;
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
      const favoriteButton=elem('button','☆ В избранное','btn btn-border vx5-favorite-toggle');
      favoriteButton.type='button';
      favoriteButton.setAttribute('aria-pressed','false');
      favoriteButton.addEventListener?.('click',()=>toggleFavorite(p));
      card.append(favoriteButton);
      cards.push({plan:p,card,compareButton,favoriteButton});
      frag.append(card);
    }
    root.replaceChildren(frag);
    for(const id of initialCompare){
      if(paid.some(plan=>plan.id===id)&&selected.size<3)selected.add(id);
    }
    show();
    updateFavorites();
    updateCompare();
    status.textContent='Платных тарифов: '+paid.length+'. Цены загружены с сервера.';
    const counter=document.getElementById('tariff-compare-label');
    if(counter)counter.textContent='Сравнить все '+plans.length+' вариантов ↗';
  }
  const update=()=>{displayLimit=12;show();};
  favoritesOnlyButton?.addEventListener('click',()=>{
    favoritesOnly=!favoritesOnly;
    updateFavorites();
    update();
  });
  shareButton?.addEventListener('click',async()=>{
    // Share only validated public plan identifiers and catalog filters.
    // Never transmit account, payment, subscription or authentication data.
    const url=new URL(window.location.href);
    const params=url.searchParams;
    for(const name of ['q','devices','sort','budget','segment','compare'])params.delete(name);
    if(search?.value.trim())params.set('q',search.value.trim().slice(0,80));
    if(device?.value!=='all')params.set('devices',device.value);
    if(sort?.value!=='days')params.set('sort',sort.value);
    if(budget?.value!=='all')params.set('budget',budget.value);
    if(selectedFilter!=='all')params.set('segment',selectedFilter);
    if(selected.size)params.set('compare',[...selected].join(','));
    // Favorites are browser-only and are intentionally not included.
    try{
      if(!navigator.clipboard?.writeText)throw Error('clipboard');
      await navigator.clipboard.writeText(url.toString());
      if(feedback)feedback.textContent='Ссылка на фильтры и сравнение скопирована.';
    }catch{
      if(feedback)feedback.textContent='Автокопирование недоступно. Скопируй ссылку из открывшегося поля.';
      if(typeof window.prompt==='function')
        window.prompt('Ссылка на подборку — скопируй её:',url.toString());
    }
  });
  for(const b of filters)b.addEventListener('click',()=>{
    const next=b.dataset.tariffFilter;
    if(['all','short','standard','long','family'].includes(next)){
      selectedFilter=next;update();
    }
  });
  search?.addEventListener('input',update);
  sort?.addEventListener('change',update);
  device?.addEventListener('change',update);
  budget?.addEventListener('change',update);
  more?.addEventListener('click',()=>{displayLimit+=12;show();});
  clear?.addEventListener('click',()=>{
    selectedFilter='all';if(search)search.value='';
    if(sort)sort.value='days';if(device)device.value='all';
    if(budget)budget.value='all';
    favoritesOnly=false;updateFavorites();
    update();search?.focus?.();
  });
  compareClear?.addEventListener('click',()=>{selected.clear();updateCompare();});
  function unavailable(){
    // Never leave legacy prices and purchase buttons on screen after an
    // unverified / failed API response.
    const message=elem('article','','tariff-unavailable');
    message.append(elem('h3','Цены временно не подтверждены'));
    message.append(elem('p','Каталог не удалось получить с сервера. Мы не показываем старые суммы или кнопки покупки как действующие.'));
    const link=elem('a','Открыть серверный каталог ↗','btn btn-border');
    link.href='https://vainahvpn-python-preview.onrender.com/plans.html';
    message.append(link);
    root.replaceChildren(message);
    if(more)more.hidden=true;
    if(empty)empty.hidden=true;
    if(compareBox)compareBox.hidden=true;
    if(count)count.textContent='Цены не подтверждены';
    if(insight)insight.textContent='Ни один тариф не считается проверенным до ответа Python API.';
    if(retryButton)retryButton.hidden=false;
  }
  async function load(){
    status.textContent='Загружаем цены с сервера…';
    if(retryButton)retryButton.hidden=true;
    // Static fallback offers may be outdated; hide them until validated.
    root.replaceChildren(elem('p','Подтверждаем актуальные цены…','tariff-loading'));
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),23000);
    try{
      const response=await fetch(apiOrigin+'/api/site/tariffs',{
        method:'GET',cache:'no-store',credentials:'omit',
        headers:{Accept:'application/json'},signal:controller.signal
      });
      if(!response.ok)throw Error('CATALOG_UNAVAILABLE');
      const data=await response.json();
      const plans=Array.isArray(data.plans)?data.plans:[];
      if(plans.length<2||data.total!==plans.length||!plans.every(safe)||
        new Set(plans.map(p=>p.id)).size!==plans.length||
        plans.filter(p=>p.status==='trial').length!==1
      )throw Error('CATALOG_INVALID');
      render(plans);
    }catch{
      unavailable();
      status.textContent='Каталог недоступен. Непроверенные цены скрыты. Нажми «Повторить загрузку».';
    }finally{clearTimeout(timer);}
  }
  retryButton?.addEventListener('click',()=>{void load();});
  async function checkCheckoutReadiness(){
    if(!checkoutReadiness)return;
    checkoutReadiness.textContent='Проверяем, какие кассы настроены…';
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),14000);
    try{
      const response=await fetch(apiOrigin+'/api/shop/config',{
        method:'GET',cache:'no-store',credentials:'omit',
        headers:{Accept:'application/json'},signal:controller.signal
      });
      if(!response.ok)throw Error('STATUS');
      const data=await response.json();
      if(typeof data?.checkout_ready!=='boolean'||
         typeof data?.platega_ready!=='boolean')throw Error('INVALID_STATUS');
      const enabled=[
        data.checkout_ready?'RollyPay':null,
        data.platega_ready?'Platega':null
      ].filter(Boolean);
      checkoutReadiness.textContent=enabled.length
        ?'Настроенные кассы: '+enabled.join(' и ')+
          '. Это проверка конфигурации, не подтверждение платежа. Итоговую доступность заказа проверь на странице оформления.'
        :'Сервер пока не разрешает оформление новых счетов. Изучение тарифов остаётся доступным.';
    }catch{
      checkoutReadiness.textContent='Не удалось получить состояние касс. Это не означает отказ в платеже; проверь страницу оформления.';
    }finally{clearTimeout(timer);}
  }
  void checkCheckoutReadiness();
  void load();
})();
