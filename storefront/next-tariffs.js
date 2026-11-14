/* Proposed Vainah VPN tariff concepts. NO checkout, NO prices, NO server writes.
   Actual sellable plans and amounts always come from the backend billing catalog. */
(() => {
  'use strict';
  const root=document.querySelector('#vx-new-offers');
  if(!root)return;
  const items=Object.freeze([
    {id:'vx-shift-15',name:'Vainah Shift',days:15,devices:3,desc:'Для коротких поездок и смены обстановки'},
    {id:'vx-month-plus-31',name:'Vainah Month+',days:31,devices:3,desc:'Месяц с дополнительным днём'},
    {id:'vx-flow-62',name:'Vainah Flow+',days:62,devices:3,desc:'Два месяца с небольшим запасом'},
    {id:'vx-focus-95',name:'Vainah Focus+',days:95,devices:3,desc:'Больше трёх месяцев'},
    {id:'vx-season-160',name:'Vainah Season',days:160,devices:3,desc:'Продолжительная подписка'},
    {id:'vx-legend-400',name:'Vainah Legend+',days:400,devices:3,desc:'Больше года без частых продлений'},
    {id:'vx-family-flex-18',name:'Vainah Family Flex',days:18,devices:6,desc:'Небольшой семейный период'},
    {id:'vx-family-month-33',name:'Vainah Family Month+',days:33,devices:6,desc:'Семейный месяц с запасом'},
    {id:'vx-family-48',name:'Vainah Family Trip',days:48,devices:6,desc:'Семейные поездки и путешествия'},
    {id:'vx-family-115',name:'Vainah Family Balance',days:115,devices:6,desc:'Гибкий срок для семьи'},
    {id:'vx-family-315',name:'Vainah Family Ultra',days:315,devices:6,desc:'На длительный срок'},
    {id:'vx-family-640',name:'Vainah Family Legend+',days:640,devices:6,desc:'Долгосрочный семейный вариант'},
  ]);
  const grid=root.querySelector('[data-vx-new-grid]');
  const count=root.querySelector('[data-vx-new-count]');
  const filters=[...root.querySelectorAll('[data-vx-new-filter]')];
  let selected='all';
  const make=(tag,text,cls='')=>{const e=document.createElement(tag);e.textContent=text;if(cls)e.className=cls;return e;};
  function render(){
    grid.replaceChildren();
    let shown=0;
    for(const item of items){
      if(selected!=='all'&&((selected==='family')!==(item.devices===6)))continue;
      const card=make('article','', 'vx-new-plan-card');
      const flag=make('span','В разработке','vx-new-plan-flag');
      const duration=make('span',item.days+' дней · до '+item.devices+' устройств','vx-new-plan-duration');
      const name=make('h3',item.name);
      const desc=make('p',item.desc);
      const pricing=make('p','Цена и дата запуска пока не установлены.','vx-new-plan-price');
      const button=make('button','Пока нельзя купить','vx-new-plan-disabled');
      button.type='button';button.disabled=true;
      card.append(flag,duration,name,desc,pricing,button);grid.append(card);shown++;
    }
    count.textContent='Предложений в подготовке: '+shown+' из '+items.length;
    filters.forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.vxNewFilter===selected)));
  }
  filters.forEach(button=>button.addEventListener('click',()=>{selected=button.dataset.vxNewFilter;render();}));
  render();
})();