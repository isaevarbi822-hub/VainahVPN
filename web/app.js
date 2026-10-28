/* Vainah VPN Next: truthful preview dashboard, zero external dependencies. */
"use strict";

const navItems = [
  ["overview","Обзор","layout-dashboard"],
  ["connect","Подключение","power"],
  ["locations","Локации","globe"],
  ["subscription","Подписка","credit-card"],
  ["devices","Мои устройства","laptop"],
  ["diagnostics","Диагностика","activity"],
  ["security","Безопасность","shield-check"],
  ["billing","Оплата","wallet"],
  ["updates","Обновления","layers"],
  ["support","Поддержка","life-buoy"],
  ["settings","Настройки","settings"]
];
const iconPaths = {
 "layout-dashboard":'<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
 "power":'<path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><path d="M12 2v10"/>',
 "globe":'<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20"/>',
 "credit-card":'<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
 "laptop":'<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M2 20h20"/>',
 "activity":'<path d="M2 12h4l3-8 6 16 3-8h4"/>',
 "shield-check":'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
 "wallet":'<rect x="2" y="5" width="20" height="16" rx="2"/><path d="M18 13h4M2 9V6a3 3 0 0 1 3-3h14"/>',
 "layers":'<path d="m12 2 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 17l9 5 9-5"/>',
 "life-buoy":'<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/><path d="m4.93 4.93 4.24 4.24m5.66 5.66 4.24 4.24m0-14.14-4.24 4.24m-5.66 5.66-4.24 4.24"/>',
 "settings":'<path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-1.86 1.86-.06-.06A1.7 1.7 0 0 0 16 18.4a1.7 1.7 0 0 0-1 .92V20h-3v-.08a1.7 1.7 0 0 0-1-1.52 1.7 1.7 0 0 0-1.88.34l-.06.06-1.86-1.86.06-.06A1.7 1.7 0 0 0 7.6 15a1.7 1.7 0 0 0-1.52-1H6v-3h.08A1.7 1.7 0 0 0 7.6 10a1.7 1.7 0 0 0-.34-1.88L7.2 8.06 9.06 6.2l.06.06A1.7 1.7 0 0 0 11 6.6a1.7 1.7 0 0 0 1-1.52V5h3v.08A1.7 1.7 0 0 0 16 6.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 1.86 1.86-.06.06A1.7 1.7 0 0 0 19.4 10a1.7 1.7 0 0 0 1.52 1H21v3h-.08A1.7 1.7 0 0 0 19.4 15Z" transform="translate(-1.5 -1.5)"/>',
 "arrow-up-right":'<path d="M7 17 17 7M7 7h10v10"/>',
 "arrow-right":'<path d="M5 12h14m-6-6 6 6-6 6"/>',
 "server":'<rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6h.01M7 17h.01"/>',
 "info":'<circle cx="12" cy="12" r="10"/><path d="M12 11v6m0-10h.01"/>',
 "clock":'<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
 "check-circle":'<circle cx="12" cy="12" r="10"/><path d="m8 12 3 3 5-6"/>',
 "alert-triangle":'<path d="m10.3 3.3-8.2 14.3A2 2 0 0 0 3.8 21h16.4a2 2 0 0 0 1.7-3.4L13.7 3.3a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4m0 4h.01"/>',
 "refresh":'<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 9a7 7 0 0 1 12-2l2 5M4 12l2 5a7 7 0 0 0 12-2"/>',
 "moon":'<path d="M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13Z"/>',
 "sun":'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>',
 "menu":'<path d="M4 6h16M4 12h16M4 18h16"/>',
 "lock":'<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
 "smartphone":'<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>',
 "download":'<path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4"/>'
};
function icon(name){return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+(iconPaths[name]||iconPaths.info)+'</svg>'}
function escapeHtml(value){return String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function badge(text,type="grey"){return '<span class="status-badge '+type+'">'+escapeHtml(text)+'</span>'}
function info(text,type=""){return '<div class="info-banner '+type+'">'+icon(type==="warning"?"alert-triangle":"info")+'<div>'+text+'</div></div>'}
function heading(section,title,desc,action=""){return '<div class="page-heading"><div><div class="eyebrow">'+escapeHtml(section)+'</div><h1>'+escapeHtml(title)+'</h1><p>'+escapeHtml(desc)+'</p></div>'+action+'</div>'}
function card(title,body,extra=""){return '<article class="card"><div class="card-head"><h2>'+title+'</h2>'+extra+'</div>'+body+'</article>'}
function empty(name,title,desc,button=""){return '<div class="empty"><div class="empty-mark">'+icon(name)+'</div><h3>'+title+'</h3><p>'+desc+'</p>'+button+'</div>'}
function linkButton(label,to,primary=false){return '<a href="#'+to+'" class="btn '+(primary?'btn-primary':'')+'" data-nav="'+to+'">'+label+' '+icon("arrow-right")+'</a>'}
const state={page:"overview",data:null,diagnostics:null,locations:null,platforms:null,security:null,error:null};

async function getJson(path){
 const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),8000);
 try{const response=await fetch(path,{signal:controller.signal,cache:"no-store"});if(!response.ok)throw new Error("HTTP "+response.status);return await response.json()}
 finally{clearTimeout(timeout)}
}
async function reload(){
 try{
  const [data,diagnostics,locations,platforms,security]=await Promise.all([
   getJson("/api/v1/overview"),getJson("/api/v1/diagnostics"),getJson("/api/v1/locations"),
   getJson("/api/v1/platforms"),getJson("/api/v1/security")
  ]);
  Object.assign(state,{data,diagnostics,locations,platforms,security,error:null});
 }catch(err){state.error=err.message||"Сеть недоступна"}
 render();
}
function notice(message){const parent=document.getElementById("toast-stack");const item=document.createElement("div");item.className="toast";item.textContent=message;parent.append(item);setTimeout(()=>item.remove(),4400)}
function renderNav(){
 document.getElementById("main-nav").innerHTML=navItems.map(([id,label,ic])=>'<a href="#'+id+'" data-nav="'+id+'" class="nav-item '+(state.page===id?"active":"")+'">'+icon(ic)+'<span>'+label+'</span>'+(id==="updates"?'<span class="nav-tag">NEW</span>':"")+'</a>').join("");
 const selected=navItems.find(x=>x[0]===state.page);
 document.getElementById("breadcrumb-current").textContent=selected?selected[1]:"Обзор";
}
function metric(ic,label,value,sub){return '<article class="card"><div class="soft-icon">'+icon(ic)+'</div><p class="metric-label">'+label+'</p><div class="metric-value">'+value+'</div><p class="metric-sub">'+sub+'</p></article>'}
function currentStatus(){return state.data?.vpn?.connected===true?'Подключён':'Не подключён'}
function overview(){
 const d=state.data;
 return heading("VAINAH NEXT / ПАНЕЛЬ","Обзор пространства","Управление сервисом Vainah VPN, состоянием подписки и будущими подключениями.",'<div class="page-actions"><button class="btn" data-action="refresh">'+icon("refresh")+' Обновить</button></div>')+
 '<section class="hero"><div class="hero-copy"><span class="hero-overline">VAINAH VPN · NEW EXPERIENCE</span><h2>Свобода сети.<br><span>Под твоим контролем.</span></h2><p>Мы пересобираем VPN с чистого листа: больше прозрачности, понятная диагностика и управление в одном месте.</p><div class="hero-actions">'+linkButton("Состояние подключения","connect",true)+linkButton("Посмотреть возможности","updates")+'</div></div><div class="hero-symbol">'+icon("shield-check")+'</div></section>'+
 '<div class="grid metrics-grid">'+metric("shield-check","Состояние VPN",currentStatus(),'<strong>Предпросмотр:</strong> нативный движок пока не подключён.')+metric("clock","Подписка","Нет данных","Подключение H1Cloud и входа — следующий этап.")+metric("server","Доступные локации",String(state.locations?.items?.length??0),"Реальные серверы ещё не загружены.")+'</div>'+
 '<div class="grid two-columns">'+card("Центр управления",'<div class="list-stack">'+[
  ["power","Подключение","Нативный туннель Android находится в разработке.",badge("Ожидает","grey")],
  ["credit-card","Подписка","Данные аккаунта станут доступны после авторизации.",badge("Нет данных","grey")],
  ["activity","Диагностика","Проверяй доступность Python API и модулей.",linkButton("Открыть","diagnostics")],
  ["shield-check","Безопасность","TLS-проверка включена. Платежи пока отключены.",linkButton("Подробнее","security")]
 ].map(([ic,note,desc,right])=>'<div class="list-row"><div class="list-icon">'+icon(ic)+'</div><div class="list-meta"><strong>'+note+'</strong><small>'+desc+'</small></div><div class="list-right">'+right+'</div></div>').join("")+'</div>')+
 card("Как устроен новый Vainah VPN",'<div class="roadmap">'+[
 ["01","Python-сервер","Личный кабинет, права доступа, диагностические API."],
 ["02","libbox на устройстве","Нативный движок, управление туннелем, счётчики."],
 ["03","H1Cloud","Серверы и подписки через защищённую интеграцию."],
 ["04","Проверенные платежи","Оплата только после тестирования безопасности."]
 ].map(([num,title,desc])=>'<div class="roadmap-item"><span class="roadmap-number">'+num+'</span><div><strong>'+title+'</strong><p>'+desc+'</p></div></div>').join("")+'</div>')+'</div>';
}
function connect(){
 return heading("ДВИЖОК / NATIVE","Подключение","Понятный статус соединения без ложных уведомлений о работающем VPN.")+
 info('<strong>Подключение ещё не доступно.</strong> Этот браузер не может запустить VPN-туннель на телефоне. Для Android собираем нативный сервис на libbox.','warning')+
 '<div class="spacer-18"></div><div class="switch-demo"><div class="power-visual">'+icon("power")+'</div><div><strong>VPN отключён</strong><span>Libbox не привязан к клиентскому приложению</span></div><button class="btn" disabled aria-disabled="true">Подключить позже</button></div>'+
 '<div class="spacer-18"></div><div class="grid equal-columns">'+card("Реальное состояние",'<div class="value-line"><span>Движок</span><strong>libbox · ожидает интеграции</strong></div><div class="value-line"><span>Активный сервер</span><strong>Нет</strong></div><div class="value-line"><span>Туннель ОС</span><strong>Не создан</strong></div><div class="value-line"><span>Интернет через VPN</span><strong>Не проверен</strong></div>')+
 card("Контроль качества",'<div class="list-stack"><div class="list-row"><div class="list-icon">'+icon("shield-check")+'</div><div class="list-meta"><strong>Только подтверждённые статусы</strong><small>«Подключён» — лишь после нативной проверки.</small></div></div><div class="list-row"><div class="list-icon">'+icon("refresh")+'</div><div class="list-meta"><strong>Переподключение</strong><small>Планируется при смене Wi-Fi / мобильной сети.</small></div></div><div class="list-row"><div class="list-icon">'+icon("activity")+'</div><div class="list-meta"><strong>Счётчики и ping</strong><small>Будут показывать реальные показатели движка.</small></div></div></div>')+'</div>';
}
function locations(){
 const items=state.locations?.items||[];
 return heading("ИНФРАСТРУКТУРА","Серверы и локации","Список доступных регионов и задержек будет приходить из твоей подписки H1Cloud.",'<div class="page-actions"><button class="btn" data-action="refresh">'+icon("refresh")+' Проверить</button></div>')+
 info('<strong>Никаких выдуманных серверов:</strong> список не заполнится, пока мы не подключим реальную подписку.')+
 '<div class="spacer-18"></div>'+card("Каталог серверов",items.length?items.map(s=>'<div class="list-row"><div class="list-icon">'+icon("globe")+'</div><div class="list-meta"><strong>'+escapeHtml(s.name||"Локация")+'</strong><small>Данные от H1Cloud</small></div></div>').join(""):empty("globe","Пока нет локаций","После подключения аккаунта и подписки здесь появятся реальные серверы, страны и результаты проверки задержки.",linkButton("Как добавить подписку","subscription"))) ;
}
function subscription(){
 return heading("АККАУНТ / VPN","Моя подписка","Данные срока подписки, лимита устройств и конфигураций будут доступны после защищённого входа.")+
 '<div class="grid equal-columns">'+card("Статус подписки",'<div class="value-line"><span>Тариф</span><strong>Не подключён</strong></div><div class="value-line"><span>Дата окончания</span><strong>—</strong></div><div class="value-line"><span>Использовано устройств</span><strong>—</strong></div><div class="value-line"><span>Провайдер</span><strong>H1Cloud · планируется</strong></div>')+
 card("Авторизация",empty("lock","Вход пока недоступен","Интеграция Clerk требует серверной проверки личности. До неё никакие персональные данные не показываем."))+'</div>'+
 '<div class="section-intro"><h2>Проверка конфигурации</h2><span>Локальный разбор формата</span></div>'+
 card("Проверить VLESS или HTTPS-ссылку",'<form id="inspect-form" autocomplete="off"><label class="field-label" for="subscription-input">VLESS-ключ или ссылка на подписку</label><textarea class="textarea" id="subscription-input" name="subscription" spellcheck="false" maxlength="65536" placeholder="vless://…  или  https://…"></textarea><div class="field-hint">Ключ отправляется в этот Python API для проверки формата, но не сохраняется. Не вводите реальные ключи на чужих публичных стендах. HTTPS-ссылку сервер не скачивает.</div><div class="field-actions"><span class="muted" style="font-size:11px">Проверка формата ≠ реальное VPN-подключение</span><button type="submit" class="btn btn-primary">'+icon("check-circle")+' Проверить формат</button></div></form><div id="inspection-result" aria-live="polite"></div>') ;
}
function devices(){
 return heading("МОИ УСТРОЙСТВА","Устройства","Управление активными устройствами и платформами — с единым представлением для аккаунта.")+
 card("Привязанные устройства",empty("laptop","Устройства не загружены","После подключения защищённого кабинета здесь появятся реальные устройства из H1Cloud."))+
 '<div class="section-intro"><h2>Платформы Vainah VPN</h2><span>План поддержки</span></div>'+
 '<div class="grid equal-columns">'+(state.platforms?.items||[]).map(p=>'<div class="card"><div class="card-head"><h2>'+escapeHtml(p.name)+'</h2>'+badge(p.state==="research"?"Изучаем":"В разработке")+'</div><p class="muted" style="font-size:12px;line-height:1.7;margin:0">'+escapeHtml(p.detail)+'</p></div>').join("")+'</div>';
}
function diagnostics(){
 const checks=state.diagnostics?.checks||[];
 return heading("СИСТЕМА / ТЕСТЫ","Диагностика","Проверки сервера, безопасности и интеграций. Статусы не заменяют тест реального VPN-туннеля.",'<button class="btn" data-action="refresh">'+icon("refresh")+' Запустить заново</button>')+
 info('<strong>Важно:</strong> работа Python API ещё не означает, что VPN-сервер доступен, а весь трафик защищён.')+
 '<div class="spacer-18"></div>'+card("Состояние компонентов",'<div class="list-stack">'+checks.map(ch=>'<div class="list-row"><div class="list-icon">'+icon(ch.state==="ok"?"check-circle":ch.state==="disabled"?"lock":"clock")+'</div><div class="list-meta"><strong>'+escapeHtml(ch.name)+'</strong><small>'+escapeHtml(ch.note)+'</small></div><div class="list-right">'+badge(ch.state==="ok"?"Работает":ch.state==="disabled"?"Отключено":"Ожидает",ch.state==="ok"?"green":"grey")+'</div></div>').join("")+'</div>')+
 '<div class="spacer-18"></div><div class="grid equal-columns">'+card("Сеть и туннель",'<div class="value-line"><span>DNS leak test</span><strong>Не выполнялся</strong></div><div class="value-line"><span>IPv6 leak test</span><strong>Не выполнялся</strong></div><div class="value-line"><span>Проверка HTTPS-выхода</span><strong>Не выполнялась</strong></div><div class="value-line"><span>Смена Wi-Fi / 4G/5G</span><strong>Не проверялась</strong></div>')+
 card("При появлении ошибки",'<div class="roadmap"><div class="roadmap-item"><span class="roadmap-number">01</span><div><strong>403 на подписке</strong><p>Проверить права, состояние запроса и ответ H1Cloud. Не означает автоматически истечение тарифа.</p></div></div><div class="roadmap-item"><span class="roadmap-number">02</span><div><strong>HTTPS timeout</strong><p>Отдельно проверить DNS, TLS и время ответа.</p></div></div><div class="roadmap-item"><span class="roadmap-number">03</span><div><strong>VPN без доступа к сети</strong><p>Проверить TUN, маршруты, DNS и исходящий трафик на устройстве.</p></div></div></div>')+'</div>';
}
function security(){
 const s=state.security||{};
 return heading("ЗАЩИТА","Безопасность","Прозрачные настройки защиты и безопасная обработка конфигураций.")+
 '<div class="grid equal-columns">'+card("Основные меры",'<div class="value-line"><span>Проверка HTTPS-сертификатов</span>'+badge(s.tls_verification?"Включена":"Неизвестно",s.tls_verification?"green":"grey")+'</div><div class="value-line"><span>Приём платежей</span>'+badge("Отключён")+'</div><div class="value-line"><span>Хранение ссылок в Python API</span>'+badge("Не сохраняются","green")+'</div><div class="value-line"><span>Нативный туннель</span>'+badge("Не подключён")+'</div>')+
 card("Политика приватности",'<p class="muted" style="font-size:12px;line-height:1.8">В демонстрационном кабинете нет личных аккаунтов, переписок, истории просмотров, реального VPN-трафика и платежей.</p>'+info('<strong>На следующих этапах:</strong> авторизация и контроль доступа, шифрованное хранилище на устройстве, минимальные логи без секретов.') )+'</div>'+
 '<div class="section-intro"><h2>Правила защиты</h2></div><div class="tip-grid">'+[
 ["lock","Ключи вне GitHub","API-токены и подписки должны находиться только в защищённых переменных и локальном хранилище."],
 ["shield-check","TLS без исключений","Никакого отключения сертификатов ради исправления ошибок 403 и timeout."],
 ["activity","Честные проверки","Показываем проверенные результаты, а не автоматически зелёные индикаторы."]
 ].map(([ic,t,d])=>'<div class="tip-card">'+icon(ic)+'<h3>'+t+'</h3><p>'+d+'</p></div>').join("")+'</div>';
}
function billing(){
 return heading("ОПЛАТА","Платежи и тарифы","Будущий центр покупок, истории операций и продления подписок.")+
 info('<strong>Оплата отключена.</strong> RollyPay появится только после проверки подписи вебхуков, повторных запросов, цен и выдачи подписки. Тестовые платежи не считаются реальными.','warning')+
 '<div class="spacer-18"></div><div class="grid equal-columns">'+card("Мои покупки",empty("credit-card","История пока пуста","Здесь будут только подтверждённые покупки авторизованного аккаунта."))+card("Продление",empty("clock","Тарифы недоступны","Никаких списаний и оформлений до включения защищённого платёжного сервиса."))+'</div>';
}
function updates(){
 return heading("ROADMAP / NEXT","Обновления","Что уже входит в новую платформу и какие компоненты предстоит подготовить.")+
 '<div class="grid equal-columns">'+card("Версия 0.1.0 · Основа",'<div class="roadmap">'+[
 ["✓","Python API","Health, диагностические API, безопасные ответы."],
 ["✓","Новый интерфейс","Адаптивный кабинет с отдельными разделами."],
 ["✓","VLESS Inspector","Проверка формата без подключения к серверу."],
 ["✓","Автотесты","Python CI и тестовые сценарии."]
 ].map(([n,t,d])=>'<div class="roadmap-item"><span class="roadmap-number">'+n+'</span><div><strong>'+t+'</strong><p>'+d+'</p></div></div>').join("")+'</div>')+
 card("Следующие этапы",'<div class="roadmap">'+[
 ["01","Аккаунт и H1Cloud","Clerk JWT, база, настоящие сроки и серверы."],
 ["02","Android libbox","Сборка нативного движка и VPN Service."],
 ["03","Стабильность соединения","DNS, IPv6, TUN, таймауты, автопереподключение."],
 ["04","Оплата и релизы","Вебхуки, тесты, подпись приложений."],
 ].map(([n,t,d])=>'<div class="roadmap-item"><span class="roadmap-number">'+n+'</span><div><strong>'+t+'</strong><p>'+d+'</p></div></div>').join("")+'</div>')+'</div>';
}
function support(){
 return heading("HELP CENTER","Помощь","База знаний для диагностики и работы с VPN, без выдачи несуществующих подключений.")+
 '<div class="tip-grid">'+[
 ["info","Ошибка 403","Отказ при получении подписки. Проверьте права доступа и серверную диагностику. Срок подписки может быть действителен."],
 ["clock","HTTPS timeout","Может зависеть от DNS, TLS, сети или недоступного сервера. Нельзя маскировать эту ошибку успешным результатом."],
 ["power","Подключён, но нет сети","Нужна проверка маршрутов, туннеля ОС, DNS и настоящего выхода в интернет."],
 ["globe","Серверов нет в списке","При обновлении подписки требуется правильный ответ H1Cloud и разбор VLESS."],
 ["laptop","Поддержка платформ","Android — первый приоритет. Windows и Apple платформы требуют отдельных движков."],
 ["shield-check","Защита данных","Не публикуйте персональные ссылки и токены в запросах поддержки или репозитории."]
 ].map(([ic,t,d])=>'<div class="tip-card">'+icon(ic)+'<h3>'+t+'</h3><p>'+d+'</p></div>').join("")+'</div>';
}
function settings(){
 return heading("ПЕРСОНАЛИЗАЦИЯ","Настройки","Локальные предпочтения интерфейса. Профиль и настройки VPN появятся после авторизации.")+
 '<div class="grid equal-columns">'+card("Оформление",'<div class="value-line"><span>Цветовая тема</span><button class="btn btn-quiet" data-action="theme">'+icon("sun")+' Сменить тему</button></div><div class="value-line"><span>Язык</span><strong>Русский</strong></div><div class="value-line"><span>Версия</span><strong>Next 0.1.0 preview</strong></div>')+
 card("Параметры VPN",'<div class="value-line"><span>Автоматическое подключение</span><strong>Ожидает движка</strong></div><div class="value-line"><span>Kill switch</span><strong>Ожидает движка</strong></div><div class="value-line"><span>Защита DNS</span><strong>Ожидает движка</strong></div>')+'</div>';
}
const pages={overview,connect,locations,subscription,devices,diagnostics,security,billing,updates,support,settings};
function render(){
 renderNav();
 const content=document.getElementById("content");
 if(state.error) {
  content.innerHTML=heading("СИСТЕМА","Не удалось загрузить данные","Python API временно недоступен.")+info('<strong>Ошибка сети:</strong> '+escapeHtml(state.error)+'. Проверьте запуск Python-сервера и повторите запрос.','error')+'<div class="spacer-18"></div><button class="btn btn-primary" data-action="refresh">'+icon("refresh")+' Повторить</button>';
 } else if(!state.data) content.innerHTML='<div class="loading-state">Загрузка данных…</div>';
 else content.innerHTML=(pages[state.page]||overview)();
}
function setPage(p){
 if(!pages[p])p="overview";
 state.page=p;render();closeMenu();
 window.scrollTo({top:0,behavior:"instant"});
}
function closeMenu(){document.body.classList.remove("menu-open");document.getElementById("menu-toggle").setAttribute("aria-expanded","false");document.getElementById("scrim").hidden=true}
function toggleTheme(){
 const next=document.documentElement.dataset.theme==="light"?"dark":"light";
 document.documentElement.dataset.theme=next;
 localStorage.setItem("vainah-theme",next);
 document.getElementById("theme-toggle").innerHTML=icon(next==="light"?"moon":"sun");
 notice(next==="light"?"Светлая тема включена":"Тёмная тема включена");
}
async function submitInspection(form){
 const input=form.querySelector("textarea");const btn=form.querySelector('button[type="submit"]');const result=document.getElementById("inspection-result");
 const value=input.value.trim();if(!value){result.innerHTML='<div class="result-panel error"><strong>Не хватает данных</strong>Введите ссылку или VLESS-ключ.</div>';return}
 btn.disabled=true;result.innerHTML='<div class="result-panel">Проверяем формат…</div>';
 const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),10000);
 try{
  const r=await fetch("/api/v1/import/inspect",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({content:value}),signal:controller.signal,cache:"no-store"});
  const j=await r.json();if(!r.ok)throw new Error(typeof j.detail==="string"?j.detail:"Ошибка проверки");
  result.innerHTML='<div class="result-panel"><strong>Формат принят</strong>'+escapeHtml(j.message)+'<div class="spacer-14"></div>Тип: '+escapeHtml(j.kind)+' · Узлов: '+Number(j.node_count||0)+((j.nodes||[]).map(n=>'<div class="value-line"><span>'+escapeHtml(n.label)+'</span><strong>'+escapeHtml(n.security.toUpperCase())+'</strong></div>').join(""))+'</div>';
 }catch(err){result.innerHTML='<div class="result-panel error"><strong>Не удалось проверить</strong>'+escapeHtml(err.message||"Ошибка сети")+'</div>'}
 finally{clearTimeout(timeout);btn.disabled=false}
}
function bind(){
 document.getElementById("menu-icon").innerHTML=icon("menu");
 const stored=localStorage.getItem("vainah-theme");document.documentElement.dataset.theme=stored==="light"?"light":"dark";
 document.getElementById("theme-toggle").innerHTML=icon(stored==="light"?"moon":"sun");
 document.getElementById("theme-toggle").addEventListener("click",toggleTheme);
 document.getElementById("menu-toggle").addEventListener("click",()=>{const open=document.body.classList.toggle("menu-open");document.getElementById("menu-toggle").setAttribute("aria-expanded",String(open));document.getElementById("scrim").hidden=!open});
 document.getElementById("scrim").addEventListener("click",closeMenu);
 document.addEventListener("click",e=>{const btn=e.target.closest("[data-action]");if(!btn)return;const a=btn.dataset.action;if(a==="refresh")reload();if(a==="theme")toggleTheme()});
 document.addEventListener("submit",e=>{if(e.target.id==="inspect-form"){e.preventDefault();submitInspection(e.target)}});
 window.addEventListener("hashchange",()=>setPage(location.hash.slice(1)));
 setPage(location.hash.slice(1)||"overview");
 reload();
}
bind();
