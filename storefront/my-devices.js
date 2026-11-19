/* Device labels only. This app cannot terminate actual VPN sessions. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const form=$('vd-form'),name=$('vd-name'),platform=$('vd-platform');
  const add=$('vd-add'),list=$('vd-list'),refresh=$('vd-refresh');
  const status=$('vd-status'),count=$('vd-count');
  const limitDisplay=$('vd-plan-limit');
  if(!form||!list)return;
  const platforms={android:'Android',ios:'iPhone / iPad',windows:'Windows',
    macos:'macOS',linux:'Linux',other:'Другое'};
  let authenticated=false,busy=false,loading=false,records=[],loadRevision=0;
  const say=message=>{status.textContent=message;};
  function element(tag,cls,content){
    const node=document.createElement(tag);node.className=cls;
    node.textContent=content||'';return node;
  }
  async function api(path,options={}){
    const {headers:customHeaders,...rest}=options;
    const controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),20000);
    try{
      const response=await fetch(path,{
        method:'GET',credentials:'same-origin',cache:'no-store',...rest,
        headers:{Accept:'application/json',...(customHeaders||{})},signal:controller.signal
      });
      const data=await response.json().catch(()=>null);
      if(!response.ok){
        const error=new Error(typeof data?.detail==='string'
          ?data.detail:'Сервер ответил '+response.status);
        error.status=response.status;
        throw error;
      }
      if(!data||typeof data!=='object')throw Error('Некорректный ответ сервера');
      return data;
    }catch(error){
      if(controller.signal.aborted)throw Error('Сервер не ответил вовремя');
      throw error;
    }finally{clearTimeout(timeout);}
  }
  function render(){
    list.replaceChildren();
    count.textContent='Записей в твоём списке: '+records.length+
      ' из 12. Это не количество активных подключений.';
    add.disabled=!authenticated||busy||loading||records.length>=12;
    if(!records.length){
      list.append(element('p','vd-muted','Устройства ещё не добавлены.'));
      return;
    }
    for(const record of records){
      if(!record||typeof record!=='object')continue;
      const row=element('article','vd-entry','');
      const details=element('div','','');
      details.append(element('strong','',String(record.name||'').slice(0,40)));
      details.append(element('small','',
        (platforms[record.platform]||'Устройство')+' · Сохранено в кабинете'));
      const rename=element('button','vd-rename','Переименовать');
      rename.type='button';
      rename.addEventListener('click',async()=>{
        if(busy||loading||!authenticated)return;
        const next=window.prompt('Новое название устройства (без VPN-ключей):',record.name);
        if(next===null)return;
        const cleaned=next.trim();
        if(!cleaned||cleaned.length>40){
          say('Название должно содержать от 1 до 40 символов.');return;
        }
        busy=true;rename.disabled=true;add.disabled=true;
        try{
          const result=await api('/api/account/devices/'+encodeURIComponent(record.id),{
            method:'PATCH',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({name:cleaned})
          });
          if(result.renamed!==true||result.vpn_disconnected!==false)throw Error('Неожиданный ответ сервера');
          if(await load())say('Название обновлено. VPN-подключение не изменено.');
        }catch(error){if(error.status===401)showLoadError(error);else say('Не удалось переименовать: '+error.message);}
        finally{busy=false;if(authenticated)render();}
      });
      const remove=element('button','vd-remove','Удалить запись (не отключает VPN)');
      remove.type='button';
      remove.addEventListener('click',async()=>{
        if(busy||loading||!authenticated)return;
        if(!window.confirm('Убрать только запись из списка? VPN-соединение останется включённым.'))return;
        busy=true;remove.disabled=true;add.disabled=true;
        try{
          const response=await api('/api/account/devices/'+encodeURIComponent(record.id),{
            method:'DELETE'
          });
          if(response.removed!==true||response.vpn_disconnected!==false)throw Error('Неожиданный ответ сервера');
          if(await load())say('Запись удалена. Настоящее VPN-подключение не изменено.');
        }catch(error){if(error.status===401)showLoadError(error);else say('Не удалось удалить запись: '+error.message);}
        finally{busy=false;if(authenticated)render();}
      });
      row.append(details,remove,rename);list.append(row);
    }
  }
  async function load(){
    if(loading)return false;
    const revision=++loadRevision;
    loading=true;
    refresh.disabled=true;
    add.disabled=true;
    if(limitDisplay)limitDisplay.textContent='Уточняем лимит тарифа…';
    try{
      const body=await api('/api/account/devices');
      if(!Array.isArray(body.items))throw Error('Сервер не вернул список устройств');
      authenticated=true;
      records=body.items.slice(0,12);
      if(limitDisplay){
        void api('/api/account/devices/limits').then(info=>{
          if(revision!==loadRevision)return;
          limitDisplay.textContent=Number.isInteger(info.plan_device_limit)
            ?'Лимит оплаченного тарифа: '+info.plan_device_limit+
              ' устройств. Количество занятых VPN-слотов неизвестно.'
            :'Лимит тарифа не подтверждён. Количество занятых VPN-слотов неизвестно.';
        }).catch(error=>{
          if(revision!==loadRevision)return;
          if(error.status===401)showLoadError(error);
          else limitDisplay.textContent='Не удалось проверить лимит. Активные VPN-сессии не отображаются.';
        });
      }
      say('Список получен. Данные об активных VPN-сессиях H1Cloud пока не доступны.');
      return true;
    }catch(error){
      showLoadError(error);
      return false;
    }finally{
      loading=false;
      refresh.disabled=false;
      if(authenticated)render();
    }
  }
  function showLoadError(error){
    loadRevision++;
    authenticated=false;
    records=[];
    list.replaceChildren(element('p','vd-muted',error.status===401
        ?'Для списка устройств сначала войди в аккаунт.'
        :'Не удалось получить список: '+error.message));
    if(error.status===401){
      const link=element('a','vd-secondary','Войти в личный кабинет');
      link.href='account.html';list.append(link);
      say('Требуется вход в Vainah VPN.');
    }else say('Список сейчас недоступен. Можно повторить загрузку.');
    add.disabled=true;
    if(limitDisplay)limitDisplay.textContent='Лимит тарифа не подтверждён.';
    count.textContent='Количество записей неизвестно.';
  }
  refresh.addEventListener('click',()=>{if(!busy)void load();});
  form.addEventListener('submit',async(event)=>{
    event.preventDefault();
    if(!authenticated||busy||loading||records.length>=12)return;
    const label=name.value.trim();
    if(!label||label.length>40)return;
    busy=true;add.disabled=true;
    try{
      const saved=await api('/api/account/devices',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:label,platform:platform.value})
      });
      if(typeof saved.id!=='string')throw Error('Сервер не подтвердил сохранение записи');
      name.value='';
      if(await load())say('Название сохранено только в твоём аккаунте. Лимит VPN не изменён.');
    }catch(error){if(error.status===401)showLoadError(error);else say('Не удалось добавить устройство: '+error.message);}
    finally{busy=false;add.disabled=!authenticated||records.length>=12;}
  });
  void load();
})();
