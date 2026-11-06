/* Vainah VPN · bounded, user-triggered HTTP reliability monitor.
   This is NOT a VPN tunnel probe. No keys, identifiers or external services.
*/
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const start=$('monitor-start'), stop=$('monitor-stop');
  if(!start||!stop)return;
  const status=$('monitor-status'), chart=$('monitor-chart');
  const details=$('monitor-detail'), copy=$('monitor-copy'), manual=$('monitor-manual');
  const stats={
    completed:$('monitor-count'),
    successes:$('monitor-success'),
    failures:$('monitor-failures'),
    avg:$('monitor-average'),
    max:$('monitor-maximum'),
    variation:$('monitor-variation')
  };
  const SAMPLE_COUNT=7, INTERVAL_MS=4000, REQUEST_TIMEOUT_MS=3000;
  let active=null, latestReport='';
  const fmt=n=>Number.isFinite(n)?new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(n):'—';
  const write=(node,text)=>{if(node)node.textContent=text;};
  function delay(ms,signal){
    return new Promise((resolve,reject)=>{
      if(signal.aborted)return reject(new Error('stopped'));
      const onAbort=()=>{clearTimeout(timer);reject(new Error('stopped'));};
      const timer=setTimeout(()=>{signal.removeEventListener('abort',onAbort);resolve();},ms);
      signal.addEventListener('abort',onAbort,{once:true});
    });
  }
  async function sample(signal){
    const local=new AbortController();
    const stopLocal=()=>local.abort();
    signal.addEventListener('abort',stopLocal,{once:true});
    const timer=setTimeout(()=>local.abort(),REQUEST_TIMEOUT_MS);
    const begun=performance.now();
    try {
      const response=await fetch('/api/health?monitor='+Math.random().toString(36).slice(2),{
        method:'GET',cache:'no-store',credentials:'omit',redirect:'error',
        headers:{Accept:'application/json'},signal:local.signal
      });
      if(!response.ok)throw new Error('HTTP '+response.status);
      const data=await response.json();
      if(data?.ok!==true)throw new Error('Invalid API response');
      return {ok:true,ms:Math.max(0,performance.now()-begun)};
    } catch(error) {
      if(signal.aborted)throw new Error('stopped');
      return {ok:false,ms:null,reason:local.signal.aborted?'Тайм-аут':error?.message||'Ошибка сети'};
    } finally {
      clearTimeout(timer);
      signal.removeEventListener('abort',stopLocal);
    }
  }
  function summarize(samples){
    const ok=samples.filter(x=>x.ok), times=ok.map(x=>x.ms);
    const avg=times.length?times.reduce((a,b)=>a+b,0)/times.length:null;
    const max=times.length?Math.max(...times):null;
    const variation=times.length>1
      ?times.slice(1).reduce((sum,value,i)=>sum+Math.abs(value-times[i]),0)/(times.length-1):null;
    return {completed:samples.length,successes:ok.length,failures:samples.length-ok.length,avg,max,variation};
  }
  function render(samples){
    const summary=summarize(samples);
    write(stats.completed,summary.completed+' / '+SAMPLE_COUNT);
    write(stats.successes,String(summary.successes));
    write(stats.failures,String(summary.failures));
    write(stats.avg,fmt(summary.avg));
    write(stats.max,fmt(summary.max));
    write(stats.variation,fmt(summary.variation));
    chart.replaceChildren();
    const maximum=Math.max(1,...samples.filter(x=>x.ok).map(x=>x.ms));
    samples.forEach((item,index)=>{
      const column=document.createElement('div');column.className='monitor-bar';
      const pole=document.createElement('span');
      pole.className=item.ok?'monitor-bar-ok':'monitor-bar-error';
      pole.style.height=item.ok?(12+Math.round(item.ms/maximum*78))+'%':'24%';
      const label=document.createElement('small');label.textContent=String(index+1);
      column.title=item.ok?fmt(item.ms)+' мс':'Нет ответа: '+item.reason;
      column.setAttribute('aria-label','Запрос '+(index+1)+': '+(item.ok?fmt(item.ms)+' миллисекунд':'ошибка'));
      column.append(pole,label);chart.append(column);
    });
    write(details,samples.length?(
      'Ответов: '+summary.successes+' из '+summary.completed+
      '. Средний HTTP-отклик: '+fmt(summary.avg)+' мс. Это не проверка подключения VPN.'
    ):'Нажми «Начать мониторинг».');
    return summary;
  }
  function makeReport(samples,reason){
    const result=summarize(samples);
    return [
      'VAINAH VPN · Монитор стабильности HTTP',
      'Статус: '+reason,
      'Проверено запросов: '+result.completed,
      'Успешно: '+result.successes,
      'Ошибок: '+result.failures,
      'Средняя задержка: '+fmt(result.avg)+' мс',
      'Максимальная задержка: '+fmt(result.max)+' мс',
      'Средний разброс соседних ответов: '+fmt(result.variation)+' мс',
      'Это наблюдение веб-API на Render, не статус VPN-сервера.'
    ].join('\n');
  }
  async function run(){
    if(active)return;
    const controller=new AbortController();
    active=controller;latestReport='';
    start.disabled=true;stop.disabled=false;copy.disabled=true;
    manual.hidden=true;
    let results=[],outcome='Завершён';
    render(results);
    try {
      for(let i=0;i<SAMPLE_COUNT;i++){
        if(controller.signal.aborted)throw new Error('stopped');
        status.textContent='Проверка '+(i+1)+' из '+SAMPLE_COUNT+'…';
        const response=await sample(controller.signal);
        results.push(response);
        render(results);
        if(i<SAMPLE_COUNT-1)await delay(INTERVAL_MS,controller.signal);
      }
      status.textContent='Мониторинг завершён. Сводка готова.';
    } catch {
      outcome='Остановлен';
      status.textContent='Мониторинг остановлен. Показаны только выполненные проверки.';
    } finally {
      latestReport=makeReport(results,outcome);
      copy.disabled=results.length===0;
      stop.disabled=true;start.disabled=false;active=null;
    }
  }
  start.addEventListener('click',run);
  stop.addEventListener('click',()=>active?.abort());
  copy.addEventListener('click',async()=>{
    if(!latestReport)return;
    try{
      if(!navigator.clipboard?.writeText)throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(latestReport);
      status.textContent='Безопасный отчёт скопирован.';
    }catch{
      manual.hidden=false;manual.value=latestReport;manual.focus();manual.select();
      status.textContent='Автоматическое копирование запрещено. Отчёт выделен для ручного копирования.';
    }
  });
  window.addEventListener('pagehide',()=>active?.abort());
  render([]);
})();
