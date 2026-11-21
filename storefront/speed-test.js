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
  const durationLimit = 45000;
  const staticOrigin='https://vainahvpn.onrender.com';
  const backendOrigin='https://vainahvpn-python-preview.onrender.com';
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
      if(response.status!==204)throw Error('Некорректный ответ проверки задержки. Открой тест на Python-сервере.');
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
    const perRound=[];
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
        if(!response.headers.get('content-type')?.startsWith('application/octet-stream'))
          throw Error('Сервер вернул не тестовые данные. Повтори на Python-сервере.');
        const body=await response.arrayBuffer();
        if(body.byteLength!==size)throw Error('Сервер вернул неполные данные.');
        bytes+=body.byteLength;
      } else {
        const body=await response.json();
        if(body.received_bytes!==size)throw Error('Передано не всё содержимое.');
        bytes+=size;
      }
      const milliseconds=performance.now()-began;
      if(!Number.isFinite(milliseconds)||milliseconds<=0)throw Error('Некорректный таймер браузера.');
      elapsed+=milliseconds;
      perRound.push(size*8/(milliseconds/1000)/1_000_000);
      bar.style.width=(starting+(ending-starting)*(i+1)/rounds)+'%';
    }
    if (elapsed<=0||perRound.length<2)throw Error('Недостаточно HTTP-проб для оценки.');
    const fastest=Math.max(...perRound),slowest=Math.min(...perRound);
    // Tiny HTTP samples cannot establish maximum ISP/VPN speed. If results
    // vary by >3x, fail the measurement instead of presenting false precision.
    if(slowest<=0||fastest/slowest>3){
      throw Error('Результаты HTTP сильно различаются. Скорость не подтверждена; повтори тест в стабильной сети.');
    }
    return {
      mbps:bytes*8/(elapsed/1000)/1_000_000,
      samples:perRound.length,
      bytes,
      ratio:fastest/slowest
    };
  }
  function reset(){
    for(const el of Object.values(results))el.textContent='—';
    bar.style.width='0%';
    latest=null;
    if(copyButton)copyButton.disabled=true;
    $('speed-explanation').textContent='Нет подтверждённых измерений. Этот тест проверяет только ограниченный HTTP-обмен с Render, а не реальную скорость интернета, VPN или вашего провайдера.';
  }
  async function run(){
    if(controller)return;
    // A static CDN cannot serve the test API. Never report its HTML/404
    // response as a successful network measurement.
    if(window.location.origin===staticOrigin){
      note('Тест переносится на сервер измерений, чтобы получить достоверный ответ API.','Переход на Python API');
      window.location.assign(backendOrigin+'/speed.html'+window.location.search+window.location.hash);
      return;
    }
    controller=new AbortController();
    const mode=document.querySelector('input[name="speed-mode"]:checked')?.value==='normal'?'normal':'eco';
    const options=$('speed-options');
    if(options)options.disabled=true;
    // At least two independently timed samples per direction are required.
    // This is a bounded diagnostic, not a professional line-speed benchmark.
    const config=mode==='eco'
      ?{pings:3,downloads:2,uploads:2,uploadBytes:128*1024}
      :{pings:5,downloads:3,uploads:3,uploadBytes:256*1024};
    start.disabled=true;
    stop.disabled=false;
    reset();
    let abortTimer;
    let timedOut=false;
    try {
      abortTimer=setTimeout(()=>{timedOut=true;controller.abort();},durationLimit);
      note('Подготавливаем сервер…','Прогрев соединения');
      const warmup=await endpoint('ping');
      check(warmup);
      if(warmup.status!==204)throw Error('Проверка не получила ожидаемый ответ Python API (204).');
      note('Измеряем задержку HTTP…','Отклик и разброс задержки');
      const latency = await timePing(config.pings);
      note('Получаем данные с сервера…','Загрузка');
      const download=await throughput('download',config.downloads,512*1024,30,68);
      results.download.textContent=format(download.mbps);
      note('Передаём данные серверу…','Отдача');
      const upload=await throughput('upload',config.uploads,config.uploadBytes,68,100);
      results.upload.textContent=format(upload.mbps);
      latest={...latency,download:download.mbps,upload:upload.mbps,mode,
        downloadSamples:download.samples,uploadSamples:upload.samples,
        downloadBytes:download.bytes,uploadBytes:upload.bytes};
      const modeNode=$('speed-network-mode');
      if(modeNode)modeNode.textContent=
        'Режим: '+(mode==='eco'?'экономный':'стандартный')+
        '. Замерены '+download.samples+' загрузки ('+(download.bytes/1048576).toFixed(2)+
        ' МиБ) и '+upload.samples+' отправки ('+(upload.bytes/1048576).toFixed(2)+
        ' МиБ). Разброс замеров может быть значительным.';
      const previousNode=$('speed-previous');
      if(previous&&previousNode&&previous.mode===latest.mode){
        const diff=(key,unit)=>{
          const change=latest[key]-previous[key];
          const sign=change>=0?'+':'';
          return sign+format(change)+' '+unit;
        };
        previousNode.textContent='По сравнению с предыдущим тестом: загрузка '+diff('download','Мбит/с')+
          ', отдача '+diff('upload','Мбит/с')+', ping '+diff('ping','мс')+'.';
      } else if(previousNode){
        previousNode.textContent=previous&&previous.mode!==latest.mode
          ?'Режим проверки изменился. Для точного сравнения выполни два теста в одном режиме.'
          :'Первый результат готов. Повтори тест с VPN включённым или выключенным для сравнения.';
      }
      previous={...latest};
      if(copyButton)copyButton.disabled=false;
      $('speed-explanation').textContent=
        'Показаны эффективные скорости маленьких HTTP-операций с сервером Render, включая ожидание ответа и обработку на сервере. Это НЕ скорость интернет-канала или VPN; короткие запросы дают приблизительные и часто заниженные результаты. Отправка оценивается по полному HTTP-запросу, а не отдельно по фактической скорости исходящего канала.';
      note('HTTP-замеры завершены. Это диагностическая оценка обмена с Render, не тест интернета или VPN.','HTTP-пробы завершены');
    } catch (error) {
      const message=timedOut?'Превышено время ответа Render. Результат не рассчитан.':
        controller.signal.aborted?'Проверка остановлена. Результат не рассчитан.':
        error.message||'Проверка не удалась.';
      reset();
      note(message,'Тест не завершён');
      $('speed-explanation').textContent='Неполные измерения сброшены, чтобы не показывать ошибочные цифры. Веб-тест не проверяет скорость VPN-туннеля.';
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
    const summary='Vainah VPN · HTTP диагностика Render'+
      '\nМедиана ответа HTTP: '+format(latest.ping)+' мс'+
      '\nРазброс HTTP: '+format(latest.jitter)+' мс'+
      '\nЭффективная скорость HTTP-загрузки: '+format(latest.download)+' Мбит/с ('+latest.downloadSamples+' пробы)'+
      '\nЭффективная скорость HTTP-отправки: '+format(latest.upload)+' Мбит/с ('+latest.uploadSamples+' пробы)'+
      '\nЭто НЕ скорость интернета, VPN-туннеля или максимальная скорость провайдера. Ожидание ответа Render включено в замер.';
    try{
      await navigator.clipboard.writeText(summary);
      note('Результат скопирован.','Тест завершён');
    }catch{
      note('Браузер не разрешил копирование. Числа доступны на экране.','Тест завершён');
    }
  });
  window.addEventListener('pagehide',()=>controller?.abort(),{once:true});
})();