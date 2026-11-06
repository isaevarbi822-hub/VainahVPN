/* Device labels only. This app cannot terminate actual VPN sessions. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const form=$('vd-form'),name=$('vd-name'),platform=$('vd-platform');
  const add=$('vd-add'),list=$('vd-list'),refresh=$('vd-refresh');
  const status=$('vd-status'),count=$('vd-count');
  if(!form||!list)return;
  const platforms={android:'Android',ios:'iPhone / iPad',windows:'Windows',
    macos:'macOS',linux:'Linux',other:'Другое'};
  let authenticated=false,busy=false,records=[];
  const say=message=>{status.textContent=message;};
  function element(tag,cls,content){
    const node=document.createElement(tag);node.className=cls;
    node.textContent=content||'';return node;
  }
  async function api(path,options={}){
    const {headers:customHeaders,...rest}=options;
    const response=await fetch(path,{
      method:'GET',credentials:'same-origin',cache:'no-store',...rest,
      headers:{Accept:'application/json',...(customHeaders||{})}
    });
    const data=await response.json().catch(()=>({}));
    if(!response.ok){
      const error=new Error(typeof data.detail==='string'
        ?data.detail:'Сервер ответил '+response.status);
      error.status=response.status;
      throw error;
    }
    return data;
  }
  function render(){
    list.replaceChildren();
    count.textContent='Записей в твоём списке: '+records.length+
      ' из 12. Это не количество активных подключений.';
    add.disabled=!authenticated||busy||records.length>=12;
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
      const rename=element('button','vd-remove','Переименовать');
      rename.type='button';
      rename.addEventListener('click',async()=>{
        if(busy||!authenticated)return;
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
          if(result.vpn_disconnected!==false)throw Error('Неожиданный ответ сервера');
          await load();
          say('Название обновлено. VPN-подключение не изменено.');
        }catch(error){say('Не удалось переименовать: '+error.message);}
        finally{busy=false;render();}
      });
      const remove=element('button','vd-remove','Удалить запись (не отключает VPN)');
      remove.type='button';
      remove.addEventListener('click',async()=>{
        if(busy||!authenticated)return;
        if(!window.confirm('Убрать только запись из списка? VPN-соединение останется включённым.'))return;
        busy=true;remove.disabled=true;add.disabled=true;
        try{
          const response=await api('/api/account/devices/'+encodeURIComponent(record.id),{
            method:'DELETE'
          });
          if(response.vpn_disconnected!==false)throw Error('Неожиданный ответ сервера');
          await load();
          say('Запись удалена. Настоящее VPN-подключение не изменено.');
        }catch(error){say('Не удалось удалить запись: '+error.message);}
        finally{busy=false;render();}
      });
      row.append(details,rename,remove);list.append(row);
    }
  }
  async function load(){
    refresh.disabled=true;
    try{
      const body=await api('/api/account/devices');
      authenticated=true;
      records=Array.isArray(body.items)?body.items.slice(0,12):[];
      say('Список получен. Данные об активных VPN-сессиях H1Cloud пока не доступны.');
      render();
    }catch(error){
      authenticated=false;
      records=[];
      list.replaceChildren();
      const note=element('p','vd-muted',error.status===401
        ?'Для списка устройств сначала войди в аккаунт.'
        :'Не удалось получить список: '+error.message);
      list.append(note);
      if(error.status===401){
        const link=element('a','vd-secondary','Войти в личный кабинет');
        link.href='account.html';list.append(link);
        say('Требуется вход в Vainah VPN.');
      }else say('Список сейчас недоступен. Устройства в VPN не изменялись.');
      renderAfterError();
    }finally{refresh.disabled=!authenticated;}
  }
  function renderAfterError(){
    add.disabled=true;
    count.textContent='Количество записей неизвестно.';
  }
  refresh.addEventListener('click',load);
  form.addEventListener('submit',async(event)=>{
    event.preventDefault();
    if(!authenticated||busy||records.length>=12)return;
    const label=name.value.trim();
    if(!label||label.length>40)return;
    busy=true;add.disabled=true;
    try{
      await api('/api/account/devices',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:label,platform:platform.value})
      });
      name.value='';
      await load();
      say('Название сохранено только в твоём аккаунте. Лимит VPN не изменён.');
    }catch(error){say('Не удалось добавить устройство: '+error.message);}
    finally{busy=false;add.disabled=!authenticated||records.length>=12;}
  });
  void load();
})();