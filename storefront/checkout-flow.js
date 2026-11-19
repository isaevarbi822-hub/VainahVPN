/* Hosted checkout: server controls both gateways; never assume paid from browser redirects. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const cards = $("shop-plans");
  if (!cards) return;
  const state = { plans: [], selected: null, config: null, gateway: "rollypay", busy: false, testOrder: null };
  const requested = new URLSearchParams(location.search);
  if (requested.get("gateway") === "platega") state.gateway = "platega";
  const money = amount => Number(amount).toLocaleString("ru-RU", {maximumFractionDigits: 2}) + " ₽";
  const dayForm = new Intl.PluralRules("ru");
  const duration = days => days + " " + ({one: "день", few: "дня", many: "дней"})[dayForm.select(days)];
  const gateways = ["rollypay", "platega"];
  let selectionRevision = 0;

  function message(text) { $("shop-payment-status").textContent = text; }
  function testMessage(text) { $("shop-test-result").textContent = text; }
  function clearIssuedLink() {
    $("shop-h1-issued-link").value = "";
    $("shop-h1-issued-link").hidden = true;
    $("shop-h1-issued-label").hidden = true;
    $("shop-h1-copy-link").hidden = true;
  }
  function explainProviderError(message) {
    const match = String(message || "").match(/^PROVIDER_HTTP_(\d{3})$/);
    if(match){
      const code = Number(match[1]);
      const reasons = {
        400:"Касса отклонила параметры или ограничения тестового счёта.",
        401:"API-ключ недействителен или запрос не авторизован.",
        403:"Касса не разрешает эту операцию.",
        404:"Платёж или маршрут API не найден.",
        409:"Конфликт запроса или повторное использование идентификатора.",
        429:"Превышен лимит запросов. Не повторяй часто.",
        500:"RollyPay вернул внутреннюю ошибку.",
        502:"Промежуточный сервер платёжного сервиса не ответил.",
        503:"RollyPay временно недоступен.",
        504:"Истекло время ожидания платёжного сервиса."
      };
      return "RollyPay HTTP " + code + ". " + (reasons[code] || "Проверить настройки кассы и доступность API.");
    }
    if(message === "PROVIDER_PAYMENT_ID_MISSING") return "Ответ RollyPay не содержит payment_id. Операция не подтверждена.";
    if(message === "PROVIDER_PAYMENT_ID_FORMAT") return "RollyPay вернул payment_id неожиданного формата. Проверка остановлена.";
    if(message === "PROVIDER_PAYMENT_STATUS_INVALID") return "RollyPay вернул неожиданный статус нового платежа. Проверка остановлена.";
    if(message === "PROVIDER_ORDER_MISMATCH") return "RollyPay вернул другой номер заказа. Статус не принят.";
    if(message === "PROVIDER_PAYMENT_MISMATCH") return "RollyPay вернул другой ID платежа. Статус не принят.";
    if(message === "PROVIDER_AMOUNT_MISMATCH") return "Сумма в RollyPay не совпадает с выбранным тарифом. Статус не принят.";
    if(message === "PROVIDER_CURRENCY_MISMATCH") return "Валюта платежа не подтверждена как RUB. Статус не принят.";
    if(message === "PROVIDER_SANDBOX_NOT_CONFIRMED") return "RollyPay вернул противоречащие тестовому заказу признаки платежа. Обработка остановлена, чтобы не принять боевой платёж за тестовый.";
    if(message === "PROVIDER_TIMEOUT") return "Истекло время ожидания ответа RollyPay.";
    if(message === "PROVIDER_NETWORK") return "Ошибка соединения с API RollyPay.";
    if(message === "PROVIDER_TERMINAL_ID_INVALID") return "ROLLYPAY_TERMINAL_ID в Render имеет неверный формат UUID. Проверь ID кассы.";
    if(message === "PROVIDER_TERMINAL_NOT_FOUND") return "RollyPay не находит кассу. Сверь Terminal ID с API-ключом.";
    if(message === "PROVIDER_TERMINAL_ID_REQUIRED") return "RollyPay требует Terminal ID. Укажи UUID кассы в Render.";
    if(message === "PROVIDER_RESPONSE_INVALID") return "RollyPay ответил, но формат данных баланса неожиданный.";
    if(message === "SANDBOX_OPERATOR_TOKEN_REQUIRED") return "Тестовый токен неверен или не заполнен. Проверь VAINAH_SANDBOX_TEST_TOKEN.";
    if(message === "VERIFIED_EMAIL_REQUIRED_FOR_AUTO_H1") return "Перед тестовой оплатой войди в аккаунт с подтверждённой почтой. Иначе система не сможет автоматически отправить VPN-ссылку.";
    if(message === "PROVIDER_NOT_CONFIGURED") return "На Python-сервере нет ROLLYPAY_API_KEY.";
    if(message === "PROVIDER_MODE_NOT_ENABLED") return "Включён локальный mock, а не RollyPay sandbox.";
    return String(message || "Неизвестная ошибка");
  }
  async function api(path, options = {}, timeout = 14000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const res = await fetch(path, {cache: "no-store", credentials: "same-origin", signal: controller.signal, ...options});
      let json;
      try { json = await res.json(); } catch { throw Error("Сервер вернул некорректный ответ."); }
      if (!res.ok) throw Error(typeof json.detail === "string" ? json.detail : "Ошибка сервера");
      return json;
    } finally {clearTimeout(timer);}
  }
  function gatewayReady(name = state.gateway) {
    return name === "platega"
      ? state.config?.platega_ready === true
      : state.config?.checkout_ready === true;
  }
  function updateGatewayControls() {
    if (!gatewayReady(state.gateway))
      state.gateway = gatewayReady("rollypay") ? "rollypay" :
        gatewayReady("platega") ? "platega" : "rollypay";
    document.querySelectorAll('input[name="shop-gateway"]').forEach(radio => {
      radio.disabled = !gatewayReady(radio.value) || state.busy;
      radio.checked = radio.value === state.gateway;
    });
    for (const gateway of gateways) {
      $(gateway + "-availability").textContent = state.config === null
        ? "Доступность уточняется"
        : gatewayReady(gateway) ? "Доступна" : "Временно недоступна";
    }
  }
  const intentKeyName = (planId, gateway) => "vainah-live-checkout-intent-v1-" +
    (gateway === "platega" ? "platega-" : "") + planId;

  async function checkExistingCheckout(planId, gateway) {
    // The token is tied to a verified email on the server; never use it as
    // evidence of payment by itself or erase an uncertain gateway request.
    const name = intentKeyName(planId, gateway);
    const key = sessionStorage.getItem(name);
    if (!key) return {found: false};
    const result = await api("/api/shop/checkout-intent?plan=" +
      encodeURIComponent(planId), {
        headers: {"Idempotency-Key": key},
        credentials: "same-origin"
      });
    if (result.renewal_ready === true &&
        result.payment_state === "paid" &&
        result.delivery_state === "delivered") {
      if (sessionStorage.getItem(name) === key) sessionStorage.removeItem(name);
    }
    return result;
  }

  function updatePaymentButton() {
    const button = $("shop-buy");
    const ready = gatewayReady();
    button.disabled = state.busy || !ready || !state.selected;
    button.textContent = state.busy ? "Открываем кассу…" :
      !ready ? "Оплата пока недоступна" :
      !state.selected ? "Выбери тариф" : "Перейти к оплате";
  }

  function authenticationRequired() {
    message("Войди по email или через Google. Если используешь Telegram, подтверди почту в кабинете. Счёт ещё не создан.");
    $("shop-login").hidden = false;
  }

  function updateCheckoutLinks() {
    if (!state.selected) return;
    const params = new URLSearchParams({plan: state.selected.id, gateway: state.gateway});
    if (history.replaceState) history.replaceState(null, "", "?" + params + (location.hash || ""));
    $("shop-login").href = "account.html?" + params + "#account-auth-panel";
  }

  async function showExistingCheckout() {
    const revision = ++selectionRevision;
    message("");
    $("shop-login").hidden = true;
    if (!state.selected || !gatewayReady()) return;
    const { id } = state.selected;
    try {
      const result = await checkExistingCheckout(id, state.gateway);
      if (revision !== selectionRevision || state.busy) return;
      if (result.renewal_ready) {
        message("Предыдущий заказ оплачен и доступ выдан. Можно оформить продление.");
      } else if (result.payment_state === "created") {
        message("Счёт уже создан. Кнопка оплаты откроет этот же счёт.");
      } else if (result.found) {
        message("Предыдущий заказ ещё обрабатывается. Проверь его статус в кабинете.");
      }
    } catch (err) {
      if (revision !== selectionRevision || state.busy) return;
      if (err.message === "VERIFIED_EMAIL_REQUIRED") authenticationRequired();
      else message("Не удалось проверить предыдущий счёт. Проверь историю заказов в кабинете.");
    }
  }

  function displayTestOrder(order) {
    clearIssuedLink();
    state.testOrder = order;
    $("shop-test-resume").value = order.order_id;
    $("shop-test-simulate").hidden = order.mode !== "mock" || order.status !== "created";
    $("shop-test-refresh").hidden = order.mode !== "provider";
    $("shop-test-payment-diagnose").hidden = order.mode !== "provider";
    $("shop-test-activation").hidden = false;
    $("shop-test-email").hidden = !(
      order.mode === "provider" && order.status === "paid" &&
      order.paid_webhook_received === true && order.owner_bound === true &&
      order.receipt_emailed !== true
    );
    testMessage("Тестовый заказ: " + order.order_id +
      "\nСтатус: " + order.status + "\nСумма: " + order.amount_rub +
      " ₽\nАккаунт: " + (order.owner_bound
        ? "привязан к подтверждённому входу" : "не привязан — войди в аккаунт до создания нового заказа") +
      "\nEmail: " + (
        order.receipt_emailed ? "тестовая квитанция автоматически отправлена" :
        order.owner_bound ? "отправится автоматически после paid webhook" :
        "не привязан к заказу"
      ) +
      (order.vpn_delivered === true
        ? "\nТестовый VPN выдан автоматически. Ссылка доступна владельцу заказа."
        : "\nVPN ещё не выдан или статус выдачи не подтверждён."));
    if(order.provider_status_fresh === false){
      const warning = order.provider_read_error === "PROVIDER_STATUS_REGRESSION"
        ? "RollyPay вернул более старый статус, чем подписанный webhook. "
        : "RollyPay временно не ответил на проверку статуса. ";
      testMessage($("shop-test-result").textContent + "\n" + warning +
        "Показан последний подписанный статус, а не свежая проверка у провайдера.");
    }
  }
  function select(id) {
    if(state.busy)return;
    const plan = state.plans.find(p => p.id === id);
    if (!plan) return;
    clearIssuedLink();
    state.selected = plan;
    document.querySelectorAll(".shop-plan").forEach(el => {
      el.setAttribute("aria-pressed", String(el.dataset.plan === id));
    });
    $("shop-selected-title").textContent = plan.title;
    $("shop-selected-days").textContent = duration(plan.days);
    $("shop-selected-devices").textContent = String(plan.devices);
    $("shop-total").textContent = money(plan.priceRub);
    updateCheckoutLinks();
    $("shop-to-payment").hidden = false;
    filterPlans();
    state.testOrder = null;
    $("shop-test-simulate").hidden = true;
    $("shop-test-refresh").hidden = true;
    $("shop-test-activation").hidden = true;
    $("shop-test-email").hidden = true;
    $("shop-test-link").hidden = true;
    $("shop-test-link").removeAttribute("href");
    testMessage("");
    updatePaymentButton();
    void showExistingCheckout();
  }
  // Filtering is display-only. Payment IDs, prices and checkout intents
  // remain exclusively server controlled and the selected order is unchanged.
  function filterPlans() {
    const query = String($("shop-plan-search")?.value || "")
      .toLocaleLowerCase("ru").trim().slice(0, 80);
    const kind = $("shop-plan-kind")?.value || "all";
    let visible = 0;
    let selectedVisible = false;
    for (const button of cards.children) {
      const plan = state.plans.find(p => p.id === button.dataset.plan);
      if (!plan) continue;
      const matchesDevice = kind === "all" ||
        (kind === "family" ? plan.devices === 6 : plan.devices === 3);
      const matchesText = (plan.title + " " + duration(plan.days) + " " +
        plan.devices + " " + (plan.devices === 6 ? "семейный" : "личный"))
        .toLocaleLowerCase("ru").includes(query);
      const match = matchesDevice && matchesText;
      button.hidden = !match;
      if (match) visible++;
      if (match && plan.id === state.selected?.id) selectedVisible = true;
    }
    const result = $("shop-plan-results");
    if (result) {
      result.textContent = visible + " из " + state.plans.length +
        " тарифов. " + (visible === 0 ? "Ничего не найдено. Очисти поиск. " : "") +
        (!selectedVisible && state.selected
          ? "Ранее выбранный тариф остаётся в итоговом заказе." : "");
    }
  }
  function applyPlanFilter() {
    // Reset only the tariff list scroll after changing the filter.
    // Never move the payment panel or the document viewport.
    cards.scrollTop = 0;
    filterPlans();
  }
  $("shop-plan-search")?.addEventListener("input", applyPlanFilter);
  $("shop-plan-kind")?.addEventListener("change", applyPlanFilter);

  function draw() {
    cards.replaceChildren();
    for (const plan of state.plans) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "shop-plan";
      button.dataset.plan = plan.id;
      button.setAttribute("aria-pressed", "false");
      const title = document.createElement("strong");
      title.textContent = plan.title;
      const subtitle = document.createElement("small");
      subtitle.textContent = "До " + plan.devices + " устройств";
      const price = document.createElement("span");
      price.className = "price";
      price.textContent = money(plan.priceRub);
      const note = document.createElement("span");
      note.className = "price-note";
      note.textContent = duration(plan.days);
      button.append(title, subtitle, price, note);
      button.addEventListener("click", () => select(plan.id));
      cards.append(button);
    }
    const planId = requested.get("plan");
    if (planId === null) select(state.plans.find(p => p.id === "30")?.id || state.plans[0].id);
    else select(planId);
    filterPlans();
    if (!state.selected) {
      $("shop-plan-results").textContent = "Тариф из ссылки недоступен. Выбери другой тариф.";
    } else if (planId !== null) {
      const selectedCard = cards.querySelector?.('[aria-pressed="true"]');
      if (selectedCard) cards.scrollTop = Math.max(0,
        selectedCard.getBoundingClientRect().top - cards.getBoundingClientRect().top - 4);
    }
  }
  async function loadPlans() {
    $("shop-plan-retry").hidden = true;
    $("shop-plan-results").textContent = "Загружаем тарифы…";
    try {
      const plans = await api("/api/shop/plans");
      if (!Array.isArray(plans.items) || !plans.items.length) throw Error("Каталог пуст");
      state.plans = plans.items;
      draw();
    } catch {
      $("shop-plan-results").textContent = "Не удалось загрузить тарифы.";
      $("shop-plan-retry").hidden = false;
    }
  }
  async function loadConfig() {
    $("shop-config-retry").hidden = true;
    $("shop-config-status").textContent = "Проверяем доступность оплаты…";
    try {
      const config = await api("/api/shop/config");
      if (typeof config?.checkout_ready !== "boolean") throw Error("Некорректные настройки оплаты");
      state.config = config;
      updateGatewayControls();
      updateCheckoutLinks();
      $("shop-config-status").textContent = gatewayReady()
        ? "Для оплаты понадобится подтверждённый email."
        : "Оформление временно недоступно. Тарифы можно посмотреть, а существующие заказы — проверить в кабинете.";
      $("shop-test-create").disabled = !config.sandbox_available;
      if (!config.sandbox_available) testMessage("Тестовая касса отключена.");
      void showExistingCheckout();
    } catch {
      $("shop-config-status").textContent = "Не удалось проверить доступность оплаты.";
      $("shop-config-retry").hidden = false;
    }
    updatePaymentButton();
  }
  $("shop-plan-retry").addEventListener("click", loadPlans);
  $("shop-config-retry").addEventListener("click", loadConfig);

  document.querySelectorAll('input[name="shop-gateway"]').forEach(radio => {
    radio.addEventListener("change", () => {
      if (state.busy || !radio.checked || !gatewayReady(radio.value)) return;
      state.gateway = radio.value;
      updateGatewayControls();
      updateCheckoutLinks();
      updatePaymentButton();
      void showExistingCheckout();
    });
  });
  $("shop-buy").addEventListener("click", async () => {
    if (state.busy || !gatewayReady() || !state.selected) return;
    state.busy = true;
    ++selectionRevision;
    message("");
    $("shop-login").hidden = true;
    updatePaymentButton();
    updateGatewayControls();
    try {
      // Reuse the same server-side intent if network timeouts or repeated
      // clicks occur: never create a second invoice for an uncertain request.
      if(!globalThis.crypto || !crypto.randomUUID){
        throw Error("Для защищённой оплаты нужен современный браузер с HTTPS.");
      }
      const planId = state.selected.id;
      const selectedGateway = state.gateway;
      const intentName = intentKeyName(planId, selectedGateway);
      const previous = await checkExistingCheckout(planId, selectedGateway);
      if (previous.found === true && previous.payment_state !== "created" &&
          previous.renewal_ready !== true) {
        message("Предыдущий заказ не завершён. Новый счёт не создан. " +
          "Проверь состояние подписки в личном кабинете.");
        return;
      }
      // A freshly created UUID is permitted only after paid+delivered or
      // when no checkout exists. A pending/ambiguous request is never reset.
      let checkoutKey = sessionStorage.getItem(intentName);
      if (!checkoutKey) {
        checkoutKey = crypto.randomUUID();
        sessionStorage.setItem(intentName, checkoutKey);
      }
      const reply = await api(
        selectedGateway === "platega" ? "/api/shop/checkout/platega" : "/api/shop/checkout", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": checkoutKey
        },
        body: JSON.stringify({plan: planId})
      });
      const url = new URL(reply.pay_url);
      if (reply.gateway !== selectedGateway || url.protocol !== "https:" ||
          url.username || url.password || url.hash || url.port) {
        throw Error("Недопустимый адрес платёжной формы");
      }
      if (selectedGateway === "rollypay") {
        if (url.hostname !== "pay.rollypay.io" ||
            !/^\/pay\/[A-Za-z0-9_-]{6,255}\/?$/.test(url.pathname) ||
            url.search) throw Error("Недопустимый адрес RollyPay");
      } else if (selectedGateway === "platega") {
        if (url.hostname !== "pay.platega.io" || url.href.length > 2048 ||
            url.pathname.includes(".."))
          throw Error("Недопустимый адрес Platega");
      } else throw Error("Неизвестная касса");
      try { sessionStorage.setItem("vainah-checkout-return", "1"); } catch {}
      location.assign(url.href);
    } catch (err) {
      if (err.message === "VERIFIED_EMAIL_REQUIRED") {
        authenticationRequired();
      } else {
        message("Не удалось открыть кассу. Проверь статус в кабинете. При повторной попытке выбери тот же тариф и кассу.");
      }
    } finally {
      state.busy = false;
      updateGatewayControls();
      updatePaymentButton();
    }
  });
  $("shop-test-diagnose").addEventListener("click", async () => {
    if(state.busy) return;
    state.busy = true;
    $("shop-test-diagnose").disabled = true;
    testMessage("Проверяем доступ к RollyPay без создания счёта…");
    try {
      const result = await api("/api/shop/sandbox/diagnostics", {
        headers: {"X-Sandbox-Token": $("shop-test-token").value}
      });
      if(result.connected){
        testMessage("Касса ответила на безопасную проверку баланса RollyPay. " +
          "API-ключ принят. Это не проверка создания платежей или автовыдачи VPN.");
      }else{
        testMessage("Проверка кассы не прошла: " + explainProviderError(result.reason) +
          "\nПроверка выполняет только GET /api/v1/balance и не создаёт платежей. " +
          "Ошибки баланса и статуса конкретного платежа — разные проверки.");
      }
    }catch(err){
      testMessage("Диагностика: " + explainProviderError(err.message));
    }finally{
      state.busy = false;
      $("shop-test-diagnose").disabled = false;
    }
  });
  $("shop-test-webhook").addEventListener("click", async () => {
    if (state.busy) return;
    state.busy = true;
    $("shop-test-webhook").disabled = true;
    testMessage("Проверяем конфигурацию webhook на Python-сервере…");
    try {
      const report = await api("/api/shop/sandbox/webhook-readiness", {
        headers: {"X-Sandbox-Token": $("shop-test-token").value}
      });
      const labels = {
        sandbox_enabled: "Sandbox",
        provider_test_enabled: "Тестовая касса RollyPay",
        signing_secret_configured: "Секрет подписи webhook",
        persistent_ledger_configured: "Постоянное хранение заказов"
      };
      const rows = Object.entries(labels).map(([key, label]) =>
        (report.checks[key] ? "✓ " : "✗ ") + label
      );
      rows.push("Адрес webhook: " + location.origin + report.webhook_path);
      rows.push("Получено подписанных webhook (тестовые заказы): " + report.verified_test_webhook_order_count);
      rows.push("Автоматическая выдача VPN (тест): " +
        (report.checks.sandbox_h1_auto_enabled ? "включена" : "отключена"));
      testMessage(rows.join(String.fromCharCode(10)));
    } catch (err) {
      testMessage("Проверка webhook: " + explainProviderError(err.message));
    } finally {
      state.busy = false;
      $("shop-test-webhook").disabled = false;
    }
  });
  $("shop-test-h1-trial").addEventListener("click", async () => {
    if(state.busy)return;
    const token = $("shop-test-token").value;
    if(!token){
      testMessage("Введи административный тестовый токен из Render.");
      return;
    }
    const accepted = window.confirm(
      "Создать один настоящий тестовый VPN-профиль в H1Cloud на 1 день и 1 устройство? " +
      "Денег не спишется. Повторная выдача заблокирована."
    );
    if(!accepted)return;
    state.busy = true;
    $("shop-test-h1-trial").disabled = true;
    $("shop-h1-issued-link").hidden = true;
    $("shop-h1-issued-label").hidden = true;
    $("shop-h1-copy-link").hidden = true;
    testMessage("Проверяем H1Cloud и выполняем одну тестовую выдачу…");
    try{
      const result = await api("/api/site/integrations/h1cloud/trial/issue", {
        method: "POST",
        headers: {
          "X-Sandbox-Token": token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({confirm:true})
      }, 40000);
      if(result.status !== "issued" || result.test_only !== true ||
         result.payment_created !== false ||
         result.days !== 1 || result.device_limit !== 1){
        throw Error("H1_TRIAL_RESPONSE_UNEXPECTED");
      }
      const url = new URL(result.subscription_url);
      if(url.protocol !== "https:" || url.username || url.password || url.hash){
        throw Error("H1_TRIAL_LINK_INVALID");
      }
      $("shop-h1-issued-link").value = url.href;
      $("shop-h1-issued-link").hidden = false;
      $("shop-h1-issued-label").hidden = false;
      $("shop-h1-copy-link").hidden = false;
      testMessage("Тестовая VPN-подписка выдана на 1 день, 1 устройство. " +
        "Создана в H1Cloud без оплаты. Скопируй ссылку и проверь подключение. " +
        "Никому не передавай адрес подписки.");
    }catch(err){
      const codes = {
        H1_TRIAL_DISABLED:"На Render не разрешён режим одноразового тестирования H1Cloud.",
        H1_TRIAL_ALREADY_ATTEMPTED:"Тест уже запускался. Вторую выдачу система заблокировала.",
        H1_TRIAL_USER_EXISTS_OR_PREFLIGHT_FAILED:"Тестовый профиль уже существует или H1Cloud отклонил предварительную проверку.",
        H1_TRIAL_WRITE_UNCERTAIN:"Неизвестно, выполнил ли H1Cloud создание. Повторно отправлять запрос нельзя: проверь панель.",
        H1_TRIAL_POSTCHECK_INVALID:"H1Cloud не подтвердил параметры подписки после создания. Нужна ручная проверка.",
        H1_TRIAL_DATABASE_UNAVAILABLE:"Не удалось сохранить результат выдачи в PostgreSQL.",
        SANDBOX_OPERATOR_TOKEN_REQUIRED:"Неверный административный тестовый токен."
      };
      testMessage("Тестовая выдача не подтверждена: " +
        (codes[err.message] || err.message || "Неизвестная ошибка"));
    }finally{
      state.busy = false;
      $("shop-test-h1-trial").disabled = false;
    }
  });
  $("shop-h1-copy-link").addEventListener("click", async () => {
    const value = $("shop-h1-issued-link").value;
    if(!value)return;
    try{
      await navigator.clipboard.writeText(value);
      testMessage("VPN-ссылка скопирована. Это приватная подписка, не публикуй её.");
    }catch{
      $("shop-h1-issued-link").select();
      testMessage("Выделена ссылка. Скопируй её вручную.");
    }
  });
  $("shop-test-create").addEventListener("click", async () => {
    if (state.busy || !state.selected || !state.config?.sandbox_available) return;
    const token = $("shop-test-token").value;
    state.busy = true;
    $("shop-test-create").disabled = true;
    $("shop-test-link").hidden = true;
    try {
      const created = await api("/api/shop/sandbox/start", {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-Sandbox-Token": token},
        body: JSON.stringify({plan: state.selected.id})
      });
      displayTestOrder(created);
      if (created.pay_url) {
        const url = new URL(created.pay_url);
        if (url.protocol !== "https:" || url.host !== "pay.rollypay.io" ||
            !/^\/pay\/[A-Za-z0-9_-]{6,255}\/?$/.test(url.pathname) || url.search || url.hash) {
          throw Error("Неверная тестовая ссылка от провайдера");
        }
        // RollyPay hosts its own payment page: navigate the top-level browser
        // instead of displaying checkout inside the Vainah VPN site.
        $("shop-test-link").href = url.href;
        $("shop-test-link").hidden = false;
        testMessage("Тестовый счёт создан. " +
          (created.owner_bound ? "Аккаунт подтверждён. " :
            "Аккаунт не привязан: это только операторский тест. ") +
          "Переходим на защищённый сайт RollyPay…");
        window.location.assign(url.href);
      }
    } catch (err) { testMessage("Не удалось создать тестовый заказ: " + explainProviderError(err.message)); }
    finally {state.busy = false; $("shop-test-create").disabled = false;}
  });
  $("shop-test-refresh").addEventListener("click", async () => {
    const order = state.testOrder;
    if (state.busy || !order || order.mode !== "provider") return;
    state.busy = true;
    $("shop-test-refresh").disabled = true;
    testMessage("Проверяем реальный тестовый статус у RollyPay…");
    try {
      const result = await api("/api/shop/sandbox/" +
        encodeURIComponent(order.order_id), {
          headers: {"X-Sandbox-Token": $("shop-test-token").value}
        });
      displayTestOrder(result);
    } catch (err) {
      testMessage("RollyPay не подтвердил статус: " + (err.message || "Ошибка сети"));
    } finally {
      state.busy = false;
      $("shop-test-refresh").disabled = false;
    }
  });
  $("shop-test-payment-diagnose").addEventListener("click", async () => {
    const order = state.testOrder;
    if(state.busy || !order || order.mode !== "provider")return;
    const token = $("shop-test-token").value;
    state.busy = true;
    $("shop-test-payment-diagnose").disabled = true;
    testMessage("Сверяем поля тестового платежа с RollyPay без оплаты и без выдачи VPN…");
    try{
      const report = await api("/api/shop/sandbox/" +
        encodeURIComponent(order.order_id) + "/payment-diagnostics", {
          headers: {"X-Sandbox-Token": token}
        });
      const labels = {
        sandbox_mode: "Тестовый режим",
        order_id: "Номер заказа",
        payment_id: "ID платежа",
        amount: "Сумма",
        currency: "Валюта",
        payment_status: "Статус"
      };
      const statuses = {
        match: "совпадает", different: "НЕ СОВПАДАЕТ",
        missing: "не передано", invalid_format: "неверный формат",
        confirmed_at_creation: "подтверждён при создании",
        contradictory: "ПРОТИВОРЕЧИТ тестовому заказу",
        recognized: "известный", unknown_or_missing: "неизвестный"
      };
      const rows = [
        "Диагностика RollyPay (только чтение)",
        "Итог: " + report.reason,
        ...Object.entries(labels).map(([field, label]) =>
          label + ": " + (statuses[report.fields[field]] || "не проверено")
        ),
        "Сумма по заказу: " + report.expected_amount_rub + " RUB",
        "Сумма в ответе RollyPay: " + (
          report.observed_amount_rub === null
            ? "не указана или недопустимый формат"
            : report.observed_amount_rub + " RUB"
        ),
        "Последнее подписанное подтверждение paid: " +
          (report.signed_paid_webhook_received ? "да" : "нет"),
        "Эта проверка не создаёт платежи и не изменяет VPN."
      ];
      testMessage(rows.join("\n"));
    }catch(err){
      testMessage("Не удалось проверить поля платежа: " +
        explainProviderError(err.message));
    }finally{
      state.busy = false;
      $("shop-test-payment-diagnose").disabled = false;
    }
  });
  $("shop-test-email").addEventListener("click", async () => {
    const order = state.testOrder;
    if (state.busy || !order || !order.owner_bound ||
        order.status !== "paid" || !order.paid_webhook_received || order.receipt_emailed) return;
    state.busy = true;
    $("shop-test-email").disabled = true;
    try {
      const result = await api(
        "/api/shop/my-test-orders/" + encodeURIComponent(order.order_id) +
        "/email-receipt", {method: "POST"}
      );
      if(result.sent !== true && result.already_sent !== true){
        testMessage("Квитанция ещё не отправлена. Дождись подтверждения выдачи VPN и повтори проверку.");
        return;
      }
      order.receipt_emailed = true;
      $("shop-test-email").hidden = true;
      testMessage(result.already_sent
        ? "Тестовое подтверждение уже отправлялось на подтверждённую почту."
        : "ТЕСТОВАЯ квитанция отправлена на подтверждённый email. " +
          "Реальных списаний не было.");
    } catch (err) {
      testMessage("Не удалось отправить тестовое письмо: " +
        (err.message === "VERIFIED_EMAIL_REQUIRED"
          ? "Сначала войди через подтверждённую почту и создай новый тестовый заказ."
          : explainProviderError(err.message)));
    } finally {
      state.busy = false;
      $("shop-test-email").disabled = false;
    }
  });
  $("shop-test-simulate").addEventListener("click", async () => {
    const order = state.testOrder;
    if (state.busy || !order || order.mode !== "mock") return;
    state.busy = true;
    try {
      const reply = await api("/api/shop/sandbox/" + encodeURIComponent(order.order_id) + "/simulate", {
        method: "POST", headers: {"X-Sandbox-Token": $("shop-test-token").value}
      });
      displayTestOrder(reply);
      testMessage("Симуляция завершена: " + reply.status +
        "\nЭто не настоящая оплата и не активная VPN-подписка.");
    } catch (err) {testMessage("Ошибка симуляции: " + (err.message || "Ошибка сети"));}
    finally {state.busy = false;}
  });
  $("shop-test-orders").addEventListener("click", async () => {
    if(state.busy) return;
    state.busy = true;
    try {
      const result = await api("/api/shop/sandbox/orders", {
        headers: {"X-Sandbox-Token": $("shop-test-token").value}
      });
      const orders = Array.isArray(result.items) ? result.items.slice(0, 10) : [];
      testMessage(orders.length
        ? "Последние тестовые заказы (без ссылок и ключей):\n" +
          orders.map(o => o.order_id + " — " + o.status + " — " +
            o.amount_rub + " ₽").join("\n") +
          "\nВведи нужный ID в поле ниже и нажми «Восстановить заказ»."
        : "Сохранённых тестовых заказов пока нет.");
    }catch(err){
      testMessage("Не удалось загрузить историю: " + explainProviderError(err.message));
    }finally{
      state.busy = false;
    }
  });
  $("shop-test-resume-button").addEventListener("click", async () => {
    if(state.busy) return;
    const id = $("shop-test-resume").value.trim();
    if(!/^vainah_test_[a-f0-9]{32}$/.test(id)){
      testMessage("Проверь ID тестового заказа.");
      return;
    }
    state.busy = true;
    try {
      const order = await api("/api/shop/sandbox/" + encodeURIComponent(id), {
        headers: {"X-Sandbox-Token": $("shop-test-token").value}
      });
      displayTestOrder(order);
      $("shop-test-link").hidden = true;
      $("shop-test-link").removeAttribute("href");
    }catch(err){
      testMessage("Не удалось восстановить заказ: " + explainProviderError(err.message));
    }finally{
      state.busy = false;
    }
  });
  $("shop-test-activation").addEventListener("click", async () => {
    if(state.busy || !state.testOrder) return;
    state.busy = true;
    const orderId = state.testOrder.order_id;
    try {
      const info = await api("/api/shop/sandbox/" +
        encodeURIComponent(orderId) + "/activation-preview", {
          headers: {"X-Sandbox-Token": $("shop-test-token").value}
        });
      const fulfillment = info.fulfillment || {};
      const issued = info.vpn_delivered === true &&
        fulfillment.status === "delivered";
      const readiness = issued
        ? "Тестовый VPN уже выдан автоматически через H1Cloud."
        : fulfillment.status === "needs_review"
          ? "Выдача остановлена: необходима проверка H1Cloud оператором."
          : fulfillment.status === "retry_pending"
            ? "Сбой до записи в H1Cloud: ожидается безопасная повторная обработка webhook."
            : fulfillment.status === "not_issued"
              ? "Оплата подтверждена, но запись о выдаче пока отсутствует."
              : fulfillment.status === "ready_for_review"
                ? "Подтверждён webhook. План подготовлен к проверке оператором."
                : "Выдача заблокирована: " + (fulfillment.reason || "нет подтверждения");
      testMessage((issued ? "Тестовая автовыдача VPN подтверждена" :
          "План выдачи VPN — только демо") +
        "\nЗаказ: " + info.order_id +
        "\nСтатус оплаты: " + info.payment_status +
        "\nПодписанный webhook: " + (fulfillment.signed_webhook_received ? "да" : "нет") +
        "\nАккаунт привязан: " + (fulfillment.customer_identity_bound ? "да" : "нет") +
        "\nEmail привязан к заказу: " + (fulfillment.verified_email_on_order ? "да" : "нет") +
        "\nКвитанция отправлена: " + (info.receipt_emailed ? "да" : "нет") +
        "\nАвтовыдача включена: " + (fulfillment.auto_provisioning_enabled ? "да" : "нет") +
        "\nПериод: " + info.duration_days + " дней" +
        "\nУстройств: " + info.device_limit +
        "\nПроверка выдачи: " + readiness +
        "\n" + info.message);
      if(issued){
        try{
          const access = await api("/api/shop/my-test-orders/" +
            encodeURIComponent(orderId) + "/vpn-access");
          const url = new URL(access.subscription_url);
          if(url.protocol !== "https:" || url.username || url.password ||
             url.hash)throw Error("SANDBOX_LINK_INVALID");
          $("shop-h1-issued-link").value = url.href;
          $("shop-h1-issued-link").hidden = false;
          $("shop-h1-issued-label").hidden = false;
          $("shop-h1-copy-link").hidden = false;
          testMessage("Тестовая VPN-подписка автоматически выдана после RollyPay. " +
            "Ссылка готова, нажми «Скопировать тестовую VPN-ссылку»; " +
            "ключ нельзя публиковать. Списание денег не происходило.");
        }catch(_error){
          testMessage("VPN автоматически создан. " +
            "Чтобы увидеть приватную ссылку, войди в тот же подтверждённый " +
            "email-аккаунт, в котором оформлялся тестовый заказ.");
        }
      }
    }catch(err){
      testMessage("План выдачи VPN не готов: " + explainProviderError(err.message));
    }finally{
      state.busy = false;
    }
  });
  void loadPlans();
  void loadConfig();
})();
