/* Diagnostic checks run only on explicit user action.
   No IP display, persistent identifiers, login tokens, or external domains. */
(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const run = byId('network-run');
  const stop = byId('network-stop');
  if (!run || !stop) return;
  const status = byId('network-status');
  const items = [
    ['internet', 'Доступность браузера'],
    ['https', 'Защита HTTPS'],
    ['api', 'Ответ сервера Vainah VPN'],
    ['ping', 'Отклик до Render'],
    ['login', 'Доступность входа по email'],
    ['shop', 'Состояние оформления заказов']
  ];
  let controller = null;
  const copy = byId('network-copy');
  const reportBox = byId('network-report');
  let lastReport = '';
  const show = (key, value, detail, state='neutral') => {
    const node=byId('network-'+key);
    if (!node) return;
    const badge=node.querySelector('[data-result]');
    const desc=node.querySelector('[data-detail]');
    if (badge) {badge.textContent=value; badge.dataset.state=state;}
    if (desc) desc.textContent=detail;
  };
  async function check(path) {
    const response=await fetch(path,{
      cache:'no-store',credentials:'omit',redirect:'error',signal:controller.signal,
      headers:{Accept:'application/json'}
    });
    if (!response.ok) throw Error('HTTP '+response.status);
    return response.json();
  }
  async function probe() {
    const a=performance.now();
    const response=await fetch('/api/health?check='+Math.random().toString(36).slice(2),{
      cache:'no-store',credentials:'omit',redirect:'error',signal:controller.signal
    });
    if (!response.ok) throw Error('HTTP '+response.status);
    const data=await response.json();
    if (data.ok !== true) throw Error('Неверный ответ API');
    return Math.round(performance.now()-a);
  }
  function prepareReport(){
    // Only fixed check labels and UI states, never tokens, email, IP or payloads.
    const lines=items.map(([key,label])=>{
      const node=byId('network-'+key);
      const state=node?.querySelector('[data-result]')?.textContent||'Не проверено';
      return label+': '+(state==='Проверяем…'?'Не завершено':state);
    });
    lastReport=['VAINAH VPN · Проверка соединения', ...lines,
      'Источник: диагностика браузера, не проверка VPN-туннеля.'].join('\\n');
    if(copy)copy.disabled=false;
  }
  async function execute(){
    if(controller)return;
    controller=new AbortController();
    lastReport='';
    if(copy)copy.disabled=true;
    if(reportBox)reportBox.hidden=true;
    run.disabled=true;stop.disabled=false;
    for(const [key] of items)show(key,'Проверяем…','', 'neutral');
    const timer=setTimeout(()=>controller?.abort(),17000);
    status.textContent='Выполняем проверки только для этого браузера…';
    try {
      show('internet',navigator.onLine?'Сеть обнаружена':'Браузер офлайн',
        navigator.onLine?'Статус браузера не гарантирует выход в интернет.':'Браузер сообщает об отсутствии сети.',
        navigator.onLine?'good':'warn');
      show('https',window.location.protocol==='https:'?'Защищённое соединение':'Без HTTPS',
        window.location.protocol==='https:'?'Страница загружена по HTTPS.':'Для реальных покупок требуется HTTPS.',
        window.location.protocol==='https:'?'good':'warn');
      const latency=await probe();
      show('api','Доступен','Проверка /api/health завершилась успешно.','good');
      show('ping',latency+' мс','Это задержка запроса к Python API, не ICMP ping.','good');
      try {
        const login=await check('/api/email-auth/config');
        const available=login.available===true;
        show('login',available?'Доступен':'Не настроен',
          available?'Можно запросить код для входа по email.':'Сервер не подтвердил доступность входа.',
          available?'good':'warn');
      } catch {
        if(controller.signal.aborted)throw Error('CHECK_ABORTED');
        show('login','Не удалось проверить','Сервис входа не ответил на безопасный запрос.','warn');
      }
      try {
        const shop=await check('/api/shop/config');
        const available=shop.checkout_ready===true;
        show('shop',available?'Оплата доступна':'Оформление недоступно',
          available?'Сервер подтвердил готовность оформления.':'Новые заказы сейчас не подтверждены сервером.',
          available?'good':'warn');
      } catch {
        if(controller.signal.aborted)throw Error('CHECK_ABORTED');
        show('shop','Не удалось проверить','Нет ответа от публичного API оплаты.','warn');
      }
      status.textContent='Готово. Проверка не создаёт заказов, не подключает VPN и не передаёт ключи.';
    } catch (error) {
      if(controller.signal.aborted)status.textContent='Проверка остановлена.';
      else status.textContent='Не удалось завершить: '+(error.message||'ошибка сети');
      for(const key of ['api','ping']){
        if(byId('network-'+key)?.querySelector('[data-result]')?.textContent==='Проверяем…')
          show(key,'Нет ответа','Проверь соединение и повтори.', 'warn');
      }
      for(const key of ['login','shop']){
        if(byId('network-'+key)?.querySelector('[data-result]')?.textContent==='Проверяем…')
          show(key,'Не проверено','Сначала необходимо соединение с API.', 'neutral');
      }
    } finally {
      clearTimeout(timer);
      prepareReport();
      controller=null;run.disabled=false;stop.disabled=true;
    }
  }
  run.addEventListener('click',execute);
  stop.addEventListener('click',()=>controller?.abort());
  if(copy)copy.addEventListener('click',async()=>{
    if(!lastReport)return;
    try{
      if(!navigator.clipboard?.writeText)throw Error('Clipboard unavailable');
      await navigator.clipboard.writeText(lastReport);
      status.textContent='Отчёт скопирован. Он не содержит VPN-ключей, адреса email и платёжных данных.';
    }catch{
      if(reportBox){
        reportBox.hidden=false;
        reportBox.value=lastReport;
        reportBox.focus();
        reportBox.select();
        status.textContent='Браузер запретил копирование. Выделенный отчёт можно скопировать вручную.';
      }else status.textContent='Не удалось скопировать отчёт.';
    }
  });
  window.addEventListener('pagehide',()=>controller?.abort(),{once:true});
})();
