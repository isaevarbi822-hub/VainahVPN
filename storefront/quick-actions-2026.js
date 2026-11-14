/* Vainah VPN 2026: progressive, account-safe accessibility and navigation layer. */
(()=>{'use strict';
if(document.documentElement.dataset.vx2026Ready)return;
document.documentElement.dataset.vx2026Ready='1';
const backend='https://vainahvpn-python-preview.onrender.com';
const publicHost='https://vainahvpn.onrender.com';
const paths=[
  ['Тарифы','/plans.html','Сравнить подписки'],
  ['Подключение','/connect.html','Настроить устройство'],
  ['Личный кабинет','/account.html','Подписка и устройства'],
  ['Помощь','/help.html','Ответы и инструкции'],
  ['Диагностика','/diagnostics.html','Проверка неполадок'],
  ['Поддержка','/support-center.html','Обратиться в поддержку']
];
const privatePages=new Set(['/account.html','/support-center.html']);
const resolve=(path)=>privatePages.has(path)?backend+path:publicHost+path;
function ready(){
  const main=document.querySelector('main')||document.querySelector('[role=main]');
  if(main&&!main.id)main.id='vx-main-content';
  if(main&&!document.querySelector('[data-vx-skip]')){
    const skip=document.createElement('a');
    skip.href='#'+main.id;skip.className='vx26-skip';skip.textContent='Перейти к содержимому';
    skip.dataset.vxSkip='';document.body.prepend(skip);
  }
  if(document.querySelector('[data-vx26-panel]'))return;
  const toggle=document.createElement('button');
  toggle.type='button';toggle.className='vx26-launch';
  toggle.textContent='Быстрые действия';toggle.setAttribute('aria-expanded','false');
  toggle.setAttribute('aria-controls','vx26-panel');
  const panel=document.createElement('section');
  panel.className='vx26-panel';panel.id='vx26-panel';panel.hidden=true;
  panel.dataset.vx26Panel='';panel.setAttribute('aria-label','Быстрые действия Vainah VPN');
  const heading=document.createElement('h2');heading.textContent='Куда перейти?';
  const intro=document.createElement('p');intro.textContent='Выберите нужный раздел. Оформление и личные данные открываются только на защищённом backend.';
  const grid=document.createElement('div');grid.className='vx26-grid';
  paths.forEach(([title,path,desc])=>{
    const a=document.createElement('a');a.href=resolve(path);
    const strong=document.createElement('strong');strong.textContent=title;
    const small=document.createElement('small');small.textContent=desc;
    a.append(strong,small);grid.append(a);
  });
  const close=document.createElement('button');close.type='button';close.className='vx26-close';close.textContent='Закрыть';
  panel.append(heading,intro,grid,close);
  const root=document.createElement('div');root.className='vx26-root';root.append(toggle,panel);document.body.append(root);
  const setOpen=open=>{panel.hidden=!open;toggle.setAttribute('aria-expanded',String(open));if(open)close.focus();else toggle.focus();};
  toggle.addEventListener('click',()=>setOpen(panel.hidden));
  close.addEventListener('click',()=>setOpen(false));
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!panel.hidden)setOpen(false);});
  document.addEventListener('pointerdown',e=>{if(!panel.hidden&&!root.contains(e.target)){panel.hidden=true;toggle.setAttribute('aria-expanded','false');}});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready,{once:true});else ready();
})();