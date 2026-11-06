/* Vainah browser-to-Render network test; no IP collection or external requests. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const start = $('speed-start'), stop = $('speed-stop');
  if (!start || !stop) return;
  const status = $('speed-status');
  const phase = $('speed-phase');
  const bar = $('speed-phase-fill');
  const results = {
    ping: $('speed-ping'),
    jitter: $('speed-jitter'),
    download: $('speed-download'),
    upload: $('speed-upload')
  };
  let controller = null;
  let previous = null;
  let latest = null;
  const copyButton = $('speed-copy');
  const durationLimit = 12000;
  const note = (text, step = '') => {
    status.textContent = text;
    if (step) phase.textContent = step;
  };
  const format = value => Number.isFinite(value) && value >= 0
    ? new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(value)
    : '—';
  const pause = () => new Promise(resolve => setTimeout(resolve, 130));
  const url = path => '/api/speedtest/' + path + '?r=' + Math.random().toString(36).slice(2);
  const endpoint = (path, options = {}) => fetch(url(path), {
    cache:'no-store', credentials:'omit', redirect:'error', signal:controller.signal,
    ...options
  });
  function check(response) {
    if (!response.ok && response.status !== 204) {
      if (response.status === 429) throw Error('Слишком много проверок. Повтори позже.');
      throw Error('Сервер недоступен (HTTP '+response.status+').');
    }
  }
  async function timePing(samples=5) {
    const values = [];
    for (let i=0; i<samples; i++) {
      const began = performance.now();
      const response = await endpoint('ping');
      check(response);
      values.push(performance.now()-began);
      bar.style.width = (7 + 23*(i+1)/samples)+'%';
      await pause();
    }
    const differences = values.slice(1).map((x,i)=>Math.abs(x-values[i]));
    const sorted = [...values].sort((a,b)=>a-b);
    const ping = sorted[Math.floor(sorted.length/2)];
    const jitter = differences.reduce((a,b)=>a+b,0)/differences.length;
    results.ping.textContent = format(ping);
    results.jitter.textContent = format(jitter);
    return {ping, jitter};
  }
  async function throughput(kind, rounds, size, starting, ending) {
    let bytes=0;
    let elapsed=0;
    for (let i=0;i<rounds;i++) {
      const began=performance.now();
      const response=kind==='download'
        ? await endpoint('download')
        : await endpoint('upload',{
          method:'POST',
          headers:{'Content-Type':'application/octet-stream'},
          body: new Uint8Array(size)
        });
      check(response);
      if (kind==='download') {
        const body=await response.arrayBuffer();
        if(body.byteLength!==size)throw Error('Сервер вернул неполные данные.');
        bytes+=body.byteLength;
      } else {
        const body=await response.json();
        if(body.received_bytes!==size)throw Error('Передано не всё содержимое.');
        bytes+=size;
      }
      elapsed+=performance.now()-began;
      bar.style.width=(starting+(ending-starting)*(i+1)/rounds)+'%';
    }
    if (elapsed<=0)throw Error('Недостаточно данных для измерения.');
    return bytes*8/(elapsed/1000)/1_000_000;
  }
  function reset(){
    for(const el of Object.values(results))el.textContent='—';
    bar.style.width='0%';
    latest=null;
    if(copyButton)copyButton.disabled=true;
    $('speed-explanation').textContent='Тест измеряет обмен данными с веб-сервером Vainah VPN на Render, а не скорость до ближайшего узла Speedtest.';
  }
  async function run(){
    controller=new AbortController();
    const mode=document.querySelector('input[name="speed-mode"]:checked')?.value==='normal'?'normal':'eco';
    const options=$('speed-options');
    if(options)options.disabled=true;
    const config=mode==='eco'?{pings:3,downloads:1,uploads:1,uploadBytes:128*1024}:{pings:5,downloads:3,uploads:2,uploadBytes:256*1024};
    start.disabled=true;
    stop.disabled=false;
    reset();
    let abortTimer;
    try {
      abortTimer=setTimeout(()=>controller.abort(),durationLimit);
      note('Измеряем задержку…','Ping и вариация задержки');
      const latency = await timePing(config.pings);
      note('Получаем данные с сервера…','Загрузка');
      const download=await throughput('download',config.downloads,512*1024,30,68);
      results.download.textContent=format(download);
      note('Передаём данные серверу…','Отдача');
      const upload=await throughput('upload',config.uploads,config.uploadBytes,68,100);
      results.upload.textContent=format(upload);
      latest={...latency,download,upload,mode};
      const modeNode=$('speed-network-mode');
      if(modeNode)modeNode.textContent='Режим: '+(mode==='eco'?'экономный':'стандартный')+'. Скорости приблизительные и зависят от нагрузки Render.';
      const previousNode=$('speed-previous');
      if(previous&&previousNode){
        const diff=(key,unit)=>{
          const change=latest[key]-previous[key];
          const sign=change>=0?'+':'';
          return sign+format(change)+' '+unit;
        };
        previousNode.textContent='По сравнению с предыдущим тестом: загрузка '+diff('download','Мбит/с')+
          ', отдача '+diff('upload','Мбит/с')+', ping '+diff('ping','мс')+'.';
      } else if(previousNode){
        previousNode.textContent='Первый результат готов. Повтори тест с VPN включённым или выключенным для сравнения.';
      }
      previous={...latest};
      if(copyButton)copyButton.disabled=false;
      note('Готово. Сравни результат с включённым и выключенным VPN.','Тест завершён');
    } catch (error) {
      note(controller.signal.aborted?'Проверка остановлена или превысила лимит времени.':
        error.message||'Проверка не удалась.','Результат неполный');
      $('speed-explanation').textContent='Показаны только завершённые этапы. Для точного сравнения проверь сеть в одинаковых условиях.';
    } finally {
      clearTimeout(abortTimer);
      controller=null;
      if(options)options.disabled=false;
      start.disabled=false;
      stop.disabled=true;
    }
  }
  start.addEventListener('click',run);
  stop.addEventListener('click',()=>{if(controller)controller.abort();});
  if(copyButton)copyButton.addEventListener('click',async()=>{
    if(!latest)return;
    const summary='Vainah VPN · Speed Lab\nPing: '+format(latest.ping)+' мс'+
      '\nJitter: '+format(latest.jitter)+' мс'+
      '\nЗагрузка: '+format(latest.download)+' Мбит/с'+
      '\nОтдача: '+format(latest.upload)+' Мбит/с'+
      '\nПроверка до Render (Франкфурт), не максимальная скорость провайдера.';
    try{
      await navigator.clipboard.writeText(summary);
      note('Результат скопирован.','Тест завершён');
    }catch{
      note('Браузер не разрешил копирование. Числа доступны на экране.','Тест завершён');
    }
  });
  window.addEventListener('pagehide',()=>controller?.abort(),{once:true});
})();