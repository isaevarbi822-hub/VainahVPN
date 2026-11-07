/* Public Vainah locations directory: never reads private subscription URLs. */
(() => {
  'use strict';
  const root=document.querySelector('[data-live-locations]');
  const input=document.getElementById('server-search');
  const favoritesButton=document.getElementById('server-only-favorites');
  const sort=document.getElementById('server-sort');
  const message=document.getElementById('server-directory-status');
  const refresh=document.getElementById('server-refresh');
  if(!root||!input||!favoritesButton||!sort||!message||!refresh)return;
  const storageKey='vainah-public-location-favorites-v1';
  const text=(tag,value,cls='')=>{
    const e=document.createElement(tag);e.textContent=String(value);
    if(cls)e.className=cls;return e;
  };
  let locations=[], favorites=new Set(),onlyFavorites=false,revision=0;
  function readFavorites(){
    try{
      const value=JSON.parse(localStorage.getItem(storageKey)||'[]');
      return new Set(Array.isArray(value)?value.filter(v=>
        typeof v==='string'&&/^[\p{L}\p{N} ._-]{1,80}$/u.test(v)).slice(0,30):[]);
    }catch{return new Set();}
  }
  function storeFavorites(){
    try{localStorage.setItem(storageKey,JSON.stringify([...favorites].slice(0,30)));}
    catch{message.textContent='Избранное работает до закрытия страницы; браузер не разрешил сохранение.';}
  }
  function safeLocation(value,index){
    if(!value||typeof value!=='object')return null;
    const name=typeof value.name==='string'?value.name.trim():'';
    if(!name||name.length>80||/[<>\r\n\u0000-\u001f]/.test(name))return null;
    const flag=typeof value.flag==='string'&&value.flag.length<=8?
      value.flag:'🌐';
    // Name comes from the operator's PUBLIC list, never private VPN keys.
    const id=name.normalize('NFC');
    return {name,id,flag,index};
  }
  function render(){
    const term=input.value.trim().toLocaleLowerCase('ru-RU').slice(0,70);
    favoritesButton.setAttribute('aria-pressed',String(onlyFavorites));
    favoritesButton.textContent=onlyFavorites?'★ Только избранные':'☆ Избранные';
    const items=locations.filter(loc=>
      (!onlyFavorites||favorites.has(loc.id))&&
      (!term||loc.name.toLocaleLowerCase('ru-RU').includes(term))
    ).sort((a,b)=>{
      const fav=Number(favorites.has(b.id))-Number(favorites.has(a.id));
      if(fav)return fav;
      return sort.value==='alpha'?
        a.name.localeCompare(b.name,'ru'):a.index-b.index;
    });
    root.replaceChildren();
    if(!locations.length){
      root.append(text('p',
        'Владелец пока не опубликовал публичный перечень локаций. Список не равен подписке клиента и не означает, что VPN-серверы недоступны.',
        'directory-empty'));
    }else if(!items.length){
      root.append(text('p','По твоему запросу локаций нет. Сбрось фильтры.','directory-empty'));
    }
    for(const loc of items){
      const article=text('article','','location');
      const flag=text('span',loc.flag,'flag');
      const details=text('div','','directory-details');
      details.append(text('strong',loc.name),text('small',
        'Публичная локация · задержка не измерена'));
      const button=text('button',favorites.has(loc.id)?'★':'☆','directory-favorite');
      button.type='button';
      button.setAttribute('aria-label',favorites.has(loc.id)?
        'Убрать из избранного: '+loc.name:'В избранное: '+loc.name);
      button.setAttribute('aria-pressed',String(favorites.has(loc.id)));
      button.addEventListener('click',()=>{
        if(favorites.has(loc.id))favorites.delete(loc.id);
        else if(favorites.size<30)favorites.add(loc.id);
        else{message.textContent='Максимум 30 публичных локаций в избранном.';return;}
        storeFavorites();render();
      });
      article.append(flag,details,button);root.append(article);
    }
    message.textContent='Показано '+items.length+' из '+locations.length+
      ' опубликованных локаций. Избранное хранится только в этом браузере.';
  }
  async function load(){
    const seq=++revision;
    message.textContent='Обновляем публичный список…';
    refresh.disabled=true;
    try{
      const response=await fetch('/api/site/locations',{
        headers:{Accept:'application/json'},cache:'no-store',credentials:'omit'
      });
      if(!response.ok)throw Error('HTTP '+response.status);
      const data=await response.json();
      if(seq!==revision)return;
      locations=Array.isArray(data.locations)?
        data.locations.slice(0,100).map(safeLocation).filter(Boolean):[];
      render();
    }catch{
      if(seq!==revision)return;
      locations=[];
      render();
      message.textContent='Не удалось проверить публичные локации. Перезагрузи список. Реальная подписка не затронута.';
    }finally{if(seq===revision)refresh.disabled=false;}
  }
  favorites=readFavorites();
  input.addEventListener('input',render);
  sort.addEventListener('change',render);
  favoritesButton.addEventListener('click',()=>{onlyFavorites=!onlyFavorites;render();});
  refresh.addEventListener('click',()=>void load());
  void load();
})();
