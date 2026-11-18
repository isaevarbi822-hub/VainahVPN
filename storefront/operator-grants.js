/* Operator-only first-party grants: no persistent storage, no browser logging. */
(() => {
  "use strict";
  const get=id=>document.getElementById(id);
  const operator=get("operator-token"),pilot=get("pilot-token");
  const check=get("check"),lock=get("lock"),issue=get("issue");
  const checkStatus=get("check-status"),grantStatus=get("grant-status");
  const result=get("result"),resultDetail=get("result-detail");
  const subscription=get("subscription"),copy=get("copy");
  let verified=false, requestId=null;
  const set=(node,message,type="")=>{node.textContent=message;node.className="status"+(type?" "+type:"");};
  function headers(){
    return {"X-Sandbox-Token":operator.value.trim(),
            "X-Live-Pilot-Token":pilot.value.trim(),
            "Accept":"application/json"};
  }
  function clear(){
    operator.value="";pilot.value="";verified=false;requestId=null;
    subscription.value="";result.hidden=true;issue.disabled=true;
    set(checkStatus,"Токены очищены. Для выдачи требуется повторная проверка.");
    set(grantStatus,"Выдача не активирована.");
  }
  async function request(path,options={}){
    const response=await fetch(path,{credentials:"omit",cache:"no-store",
      ...options,headers:{...headers(),...(options.headers||{})}});
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"Ошибка API ("+response.status+")");
    return data;
  }
  check.addEventListener("click",async()=>{
    verified=false;issue.disabled=true;result.hidden=true;
    if(operator.value.trim().length<24||pilot.value.trim().length<32||
        operator.value.trim()===pilot.value.trim()){
      set(checkStatus,"Нужны два разных длинных операторских токена.","error");return;
    }
    check.disabled=true;
    set(checkStatus,"Проверяем права доступа и конфигурацию H1Cloud...");
    try{
      const state=await request("/api/operator/manual-grants/status");
      if(!state.ready)throw Error(state.reason||"GRANT_NOT_READY");
      verified=true;issue.disabled=false;
      set(checkStatus,"Разрешено: ручная выдача активна. H1Cloud и база настроены.","success");
      set(grantStatus,"Выбери email, срок и устройства, затем подтверди выдачу.");
    }catch(e){set(checkStatus,"Недоступно: "+e.message,"error");}
    finally{check.disabled=false;}
  });
  lock.addEventListener("click",clear);
  for(const input of [operator,pilot]){
    input.addEventListener("input",()=>{
      verified=false;issue.disabled=true;
      set(checkStatus,"Токен изменён. Требуется повторная проверка.");
    });
  }
  get("grant-form").addEventListener("submit",async(event)=>{
    event.preventDefault();
    if(!verified)return;
    if(!get("confirm").checked)return;
    const email=get("recipient").value.trim();
    const days=Number(get("days").value),devices=Number(get("devices").value);
    if(!email||![1,7,30,90,180,365].includes(days)||![1,2,3,6].includes(devices)){
      set(grantStatus,"Проверь email, срок и лимит устройств.","error");return;
    }
    // Keep the generated ID on this page: a status lookup is safe after a timeout.
    requestId=crypto.randomUUID().replace(/-/g,"");
    issue.disabled=true;result.hidden=true;subscription.value="";
    set(grantStatus,"Создаём защищённую заявку и проверяем H1Cloud...");
    try{
      const data=await request("/api/operator/manual-grants/issue",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({recipient_email:email,grant_id:requestId,
          days,devices,confirm:true}),
      });
      showIssued(data);
    }catch(e){
      set(grantStatus,"Выдача не подтверждена: "+e.message+
        ". НЕ создавай новую заявку, если был сетевой сбой. Проверь результат ниже.","error");
      result.hidden=false;
      resultDetail.textContent="ID проверки: "+requestId+
        ". Ссылка появится только после подтверждённой записи. Нажми «Проверить результат».";
      subscription.value="";
    }finally{issue.disabled=!verified;}
  });
  function showIssued(data){
    if(data.status!=="issued"||!data.subscription_url||
        !data.subscription_url.startsWith("https://"))throw Error("GRANT_RESULT_INVALID");
    subscription.value=data.subscription_url;result.hidden=false;
    const expiry=new Date(data.expires_at);
    const date=Number.isNaN(expiry.getTime())?"неизвестно":expiry.toLocaleString("ru-RU");
    resultDetail.textContent="Подписка подтверждена H1Cloud · "+data.days+
      " дней · "+data.devices+" устройств · до "+date+
      (data.email_sent?" · Email отправлен":" · Email не отправлен: передай ссылку вручную");
    set(grantStatus,"Готово. Подписка выдана; заявка "+(data.grant_id||requestId)+".","success");
  }
  const verify=document.createElement("button");
  verify.type="button";verify.id="verify-issue";verify.textContent="Проверить результат";
  verify.className="ghost";
  verify.addEventListener("click",async()=>{
    if(!verified||!requestId)return;
    verify.disabled=true;
    try{
      const state=await request("/api/operator/manual-grants/"+requestId);
      if(state.status==="issued")showIssued(state);
      else set(grantStatus,"Состояние "+state.status+
        ". Новую заявку не создавай: требуется проверка H1Cloud.","error");
    }catch(e){set(grantStatus,"Проверка недоступна: "+e.message,"error");}
    finally{verify.disabled=false;}
  });
  get("result").querySelector(".actions").append(verify);
  copy.addEventListener("click",async()=>{
    if(!subscription.value)return;
    try{
      await navigator.clipboard.writeText(subscription.value);
      set(grantStatus,"Личная ссылка скопирована. Не публикуй её открыто.","success");
    }catch{subscription.focus();subscription.select();set(grantStatus,
      "Браузер запретил копирование. Выдели ссылку и скопируй вручную.");}
  });
  window.addEventListener("pagehide",clear);
})();
