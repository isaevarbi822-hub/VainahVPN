/* Vainah Check: no secrets, no local storage, no simulated server pings. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const stamp = () => new Intl.DateTimeFormat('ru-RU',{
    hour:'2-digit',minute:'2-digit',second:'2-digit'
  }).format(new Date());
  const STATES={
    ok:'Проверка пройдена',
    attention:'Нужно внимание',
    unknown:'Нет подтверждения',
    information:'Информация',
  };
  const setState=(id,text,state='unknown')=>{
    const el=$(id);
    if(!el)return;
    el.textContent=text;
    el.dataset.state=state;
  };
  const text=(id,message)=>{const el=$(id);if(el)el.textContent=message;};
  function node(tag,cls,content){
    const el=document.createElement(tag);
    el.className=cls;
    el.textContent=String(content??'');
    return el;
  }
  async function json(url,authenticated=false){
    const response=await fetch(url,{
      method:'GET',credentials:authenticated?'same-origin':'omit',
      cache:'no-store',headers:{Accept:'application/json'},
      signal:AbortSignal.timeout(16000),
    });
    if(!response.ok){
      const err=new Error('HTTP '+response.status);err.status=response.status;throw err;
    }
    return response.json();
  }
  let infraRevision=0,accountRevision=0;
  async function infrastructure(){
    const revision=++infraRevision,button=$('check-run');
    button.disabled=true;
    setState('infra-overall','Проверяем…','unknown');
    text('check-updated','Запрос к сайту отправлен.');
    try{
      const info=await json('/api/site/check/summary');
      if(revision!==infraRevision)return;
      const target=$('infra-list');target.replaceChildren();
      for(const item of Array.isArray(info.checks)?info.checks:[]){
        if(!item||typeof item!=='object')continue;
        const card=node('article','entry','');
        const detail=node('div','','');
        detail.append(node('strong','',item.title),node('p','',item.note));
        const status=node('span','pill',STATES[item.state]||'Неизвестно');
        status.dataset.state=['ok','attention'].includes(item.state)?item.state:'unknown';
        card.append(detail,status);target.append(card);
      }
      if(!target.childNodes.length)target.append(node('p','empty','Нет данных.'));
      const problem=info.summary==='attention';
      const allOk=info.summary==='control_plane_checks_ok';
      setState('infra-overall',
        problem?'Есть проблемы API':allOk?'API проверены':'Часть проверок недоступна',
        problem?'attention':allOk?'ok':'unknown');
      text('check-updated','Ответ получен: '+stamp()+
        '. Проверены служебные API, не работа VPN-туннелей.');
    }catch{
      if(revision!==infraRevision)return;
      $('infra-list').replaceChildren(node('p','empty',
        'Не удалось получить статус API. Проверь подключение к интернету и повтори.'));
      setState('infra-overall','Данные недоступны','unknown');
      text('check-updated','Проверка не завершилась. Не делай вывод о работоспособности VPN.');
    }finally{
      if(revision===infraRevision)button.disabled=false;
    }
  }
  async function account(){
    const revision=++accountRevision,button=$('check-account');
    button.disabled=true;
    setState('account-state','Проверяем…','unknown');
    $('account-result').replaceChildren(node('p','empty','Проверяем выданную подписку…'));
    try{
      const result=await json('/api/account/connection-check',true);
      if(revision!==accountRevision)return;
      const target=$('account-result'),section=node('article','entry','');
      const content=node('div','','');
      content.append(node('strong','result-title',result.headline),
        node('p','detail',result.next_step));
      if(Number.isInteger(result.traffic_used_percent)){
        content.append(node('p','detail',
          'Подтверждённое использование трафика: '+result.traffic_used_percent+'% лимита.'));
      }
      if(typeof result.expires_at==='string'){
        const date=new Date(result.expires_at);
        if(Number.isFinite(date.getTime())){
          content.append(node('p','detail','Дата H1Cloud: '+date.toLocaleDateString('ru-RU')));
        }
      }
      content.append(node('p','small','VPN-туннель на устройстве этим не проверяется.'));
      section.append(content);
      target.replaceChildren(section);
      setState('account-state',
        result.level==='ok'?'Профиль активен':result.level==='attention'?'Нужна проверка':'Статус уточняется',
        result.level);
    }catch(error){
      if(revision!==accountRevision)return;
      if(error.status===401){
        setState('account-state','Нужен вход','unknown');
        $('account-result').replaceChildren(node('p','empty',
          'Войди в личный кабинет по подтверждённой почте или Telegram, затем повтори проверку.'));
      }else{
        setState('account-state','Нет данных','unknown');
        $('account-result').replaceChildren(node('p','empty',
          'Проверить профиль сейчас не удалось. Это не означает, что подписка истекла.'));
      }
    }finally{
      if(revision===accountRevision)button.disabled=false;
    }
  }
  async function browserPing(){
    const button=$('browser-run');
    button.disabled=true;setState('browser-state','Проверяем','unknown');
    text('browser-result','Отправляем короткий запрос к сайту…');
    try{
      const started=performance.now();
      const response=await fetch('/api/speedtest/ping',{
        method:'GET',cache:'no-store',credentials:'omit',
        signal:AbortSignal.timeout(12000)
      });
      const elapsed=Math.round(performance.now()-started);
      if(response.status===429){
        setState('browser-state','Лимит измерений','unknown');
        text('browser-result','Слишком много запросов. Попробуй позже.');
      }else if(response.status===204){
        setState('browser-state','Сайт отвечает','ok');
        text('browser-result','Ответ от сайта Render: около '+elapsed+
          ' мс. Это не задержка до VPN-сервера.');
      }else throw Error('probe failed');
    }catch{
      setState('browser-state','Нет ответа','unknown');
      text('browser-result','Сайт не ответил на пробу. Это не доказывает сбой VPN-сервера.');
    }finally{button.disabled=false;}
  }
  async function serverReady(){
    try{
      const data=await json('/api/site/check/server-selection');
      setState('server-state',data.available===true?'Есть измерения':'Автовыбор недоступен',
        data.available===true?'ok':'unknown');
      text('server-result',typeof data.reason==='string'?data.reason:
        'Проверенных данных об отдельных VPN-серверах нет.');
    }catch{
      setState('server-state','Нет данных','unknown');
      text('server-result','Не удалось проверить поддержку автовыбора серверов.');
    }
  }
  $('check-run').addEventListener('click',()=>void infrastructure());
  $('check-account').addEventListener('click',()=>void account());
  $('browser-run').addEventListener('click',()=>void browserPing());
  void serverReady();
})();
