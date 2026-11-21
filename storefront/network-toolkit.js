/* Vainah VPN Network Tools. All values stay inside the browser tab. */
(() => {
  'use strict';
  const root=document.getElementById('network-toolkit');
  if(!root)return;
  const $=(s,base=root)=>base.querySelector(s);
  const forms=[...root.querySelectorAll('form[data-calculator]')];
  const results=new Map();
  const history=$('#nt-history'),copy=$('#nt-copy'),clear=$('#nt-clear'),manual=$('#nt-manual');
  const notice=$('#nt-notice');
  const fmt=n=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(n);
  function amount(form,name){
    const field=form.querySelector('[name="'+name+'"]');
    const value=Number(field?.value);
    if(!field||!field.value.trim()||!Number.isFinite(value)||value<0||value>1e9)throw Error('Введи корректные неотрицательные числа.');
    return value;
  }
  function positive(form,name){
    const v=amount(form,name);
    if(v<=0)throw Error('Значение должно быть больше нуля.');
    return v;
  }
  function duration(s){
    if(!Number.isFinite(s)||s<0)return '—';
    const rounded=Math.max(1,Math.ceil(s));
    if(rounded>=86400)return fmt(rounded/86400)+' дн.';
    const h=Math.floor(rounded/3600),m=Math.floor((rounded%3600)/60),sec=rounded%60;
    return (h?h+' ч ':'')+(m?m+' мин ':'')+(sec||(!h&&!m)?sec+' с':'');
  }
  const handlers={
    convert(form){
      const mbps=amount(form,'mbps');
      return [fmt(mbps/8)+' МБ/с',
        'Примерно '+fmt(mbps*1e6/(8*1048576))+' МиБ/с. 8 бит = 1 байт.'];
    },
    download(form){
      const size=positive(form,'size'),speed=positive(form,'speed');
      const unit=form.querySelector('[name="unit"]')?.value;
      const bytes=size*(unit==='gib'?1024**3:1024**2);
      return [duration(bytes*8/(speed*1e6)),
        'Оценка для '+fmt(size)+' '+(unit==='gib'?'ГиБ':'МиБ')+' при '+fmt(speed)+' Мбит/с.'];
    },
    upload(form){
      const size=positive(form,'size'),speed=positive(form,'speed');
      const unit=form.querySelector('[name="unit"]')?.value;
      const bytes=size*(unit==='gib'?1024**3:1024**2);
      return [duration(bytes*8/(speed*1e6)),
        'Оценка отдачи при '+fmt(speed)+' Мбит/с без учёта дополнительного протокольного трафика.'];
    },
    stream(form){
      const speed=positive(form,'rate'),hours=positive(form,'hours');
      const bytes=speed*1e6*hours*3600/8;
      return [fmt(bytes/1e9)+' ГБ',
        'Примерно '+fmt(bytes/(1024**3))+' ГиБ при непрерывной передаче данных.'];
    },
    quota(form){
      const limit=positive(form,'limit'),used=amount(form,'used');
      const remaining=Math.max(0,limit-used);
      const percent=Math.round(used/limit*100);
      return [fmt(remaining)+' ГиБ осталось',
        'Израсходовано '+fmt(used)+' из '+fmt(limit)+' ГиБ ('+percent+'%). '+
        (used>limit?'Указанный расход превышает лимит.':'Это расчёт по введённым вручную данным.')];
    },
    daily(form){
      const remaining=amount(form,'remaining'),days=positive(form,'days');
      return [fmt(remaining/days)+' ГиБ в день',
        'Чтобы распределить '+fmt(remaining)+' ГиБ на '+fmt(days)+' дн., ориентируйся на этот средний дневной бюджет.'];
    },
    monthly(form){
      const daily=amount(form,'daily'),days=positive(form,'days');
      if(!Number.isInteger(days))throw Error('Количество дней должно быть целым числом.');
      return [fmt(daily*days)+' ГиБ за период',
        'Планирование на '+fmt(days)+' дн. Это прогноз по введённому расходу, а не счётчик H1Cloud.'];
    },
    lifespan(form){
      const remaining=amount(form,'remaining'),daily=positive(form,'daily');
      return [fmt(remaining/daily)+' дн.',
        'Если использовать в среднем '+fmt(daily)+' ГиБ ежедневно, оставшегося лимита хватит примерно на указанный срок.'];
    },
    devices(form){
      const limit=positive(form,'limit'),devices=positive(form,'devices');
      if(!Number.isInteger(devices)||devices>100)throw Error('Количество устройств: целое число от 1 до 100.');
      return [fmt(limit/devices)+' ГиБ на устройство',
        'Равномерное планирование для '+devices+' устройств. Это не настройка серверных ограничений.'];
    },
    backup(form){
      const size=positive(form,'size'),speed=positive(form,'speed'),limit=positive(form,'limit');
      const seconds=size*(1024**3)*8/(speed*1e6);
      const percent=Math.round(size/limit*100);
      return [duration(seconds),
        'Резервная копия займёт '+fmt(percent)+'% указанного лимита. Без учёта накладных расходов и повторных передач.'];
    },
    compare(form){
      const direct=positive(form,'direct'),vpn=amount(form,'vpn');
      const delta=(vpn/direct-1)*100;
      return [(delta>0?'+':'')+fmt(delta)+'%',
        'Скорость '+(delta<0?'ниже':'выше или равна')+' относительно указанной без VPN. Сравнивай при одинаковых условиях.'];
    },
    latency(form){
      const direct=positive(form,'direct'),vpn=amount(form,'vpn');
      const delta=vpn-direct;
      return [(delta>0?'+':'')+fmt(delta)+' мс',
        'Изменение задержки: '+(delta>0?'увеличилась':'уменьшилась или не изменилась')+
        ' на '+fmt(Math.abs(delta/direct*100))+'%. Данные вводятся вручную.'];
    }
  };
  function updateHistory(){
    history.replaceChildren();
    const entries=[...results.values()].slice(-12).reverse();
    if(!entries.length){const li=document.createElement('li');li.textContent='Пока нет расчётов.';history.append(li);}
    else for(const x of entries){
      const li=document.createElement('li');
      li.textContent=x.label+': '+x.result;
      history.append(li);
    }
    copy.disabled=!entries.length;
    clear.disabled=!entries.length;
  }
  for(const form of forms){
    form.addEventListener('submit',event=>{
      event.preventDefault();
      const name=form.dataset.calculator,fn=handlers[name];
      const label=form.querySelector('h2')?.textContent?.trim()||name;
      const output=form.querySelector('[data-result]');
      const detail=form.querySelector('[data-detail]');
      if(!fn)return;
      try{
        const [value,note]=fn(form);
        if(!Number.isFinite(Number(value))&&value==='NaN')throw Error('Получился некорректный результат.');
        output.textContent=value;
        detail.textContent=note;
        results.delete(name);
        results.set(name,{label,result:value,note});
        notice.textContent='Готово. Все расчёты выполняются в этой вкладке.';
      }catch(error){
        output.textContent='—';
        detail.textContent=error.message||'Проверь исходные значения.';
        results.delete(name);
        notice.textContent='Проверь введённые данные и повтори расчёт.';
      }
      updateHistory();
    });
  }
  copy.addEventListener('click',async()=>{
    const content=['VAINAH VPN · Сетевые расчёты',
      ...[...results.values()].map(item=>item.label+': '+item.result+' ('+item.note+')'),
      'Результаты приблизительные и основаны на введённых вручную значениях.'].join('\n');
    try{
      if(!navigator.clipboard?.writeText)throw Error('No clipboard');
      await navigator.clipboard.writeText(content);
      notice.textContent='Сводка скопирована без VPN-ключей и личных данных.';
    }catch{
      manual.hidden=false;manual.value=content;manual.focus();manual.select();
      notice.textContent='Скопируй выделенный текст вручную.';
    }
  });
  clear.addEventListener('click',()=>{
    results.clear();forms.forEach(f=>{f.reset();
      const out=f.querySelector('[data-result]');if(out)out.textContent='—';
      const detail=f.querySelector('[data-detail]');if(detail)detail.textContent='Укажи значения и нажми «Рассчитать».';
    });
    manual.hidden=true;manual.value='';
    notice.textContent='Локальные расчёты сброшены.';
    updateHistory();
  });
  updateHistory();
})();