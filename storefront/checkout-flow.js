/* RollyPay checkout: public live charge remains disabled until secure fulfillment. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const cards = $("shop-plans");
  if (!cards) return;
  const state = { plans: [], selected: null, config: null, busy: false, testOrder: null };
  const money = amount => Number(amount).toLocaleString("ru-RU", {maximumFractionDigits: 0}) + " ₽";
  function message(text) { $("shop-config-status").textContent = text; }
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
    if(message === "PROVIDER_NOT_CONFIGURED") return "На Python-сервере нет ROLLYPAY_API_KEY.";
    if(message === "PROVIDER_MODE_NOT_ENABLED") return "Включён локальный mock, а не RollyPay sandbox.";
    return String(message || "Неизвестная ошибка");
  }
  async function api(path, options = {}, timeout = 14000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const res = await fetch(path, {cache: "no-store", signal: controller.signal, ...options});
      let json;
      try { json = await res.json(); } catch { throw Error("Сервер вернул некорректный ответ."); }
      if (!res.ok) throw Error(typeof json.detail === "string" ? json.detail : "Ошибка сервера");
      return json;
    } finally {clearTimeout(timer);}
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
    $("shop-selected-days").textContent = plan.days + " дней";
    $("shop-selected-devices").textContent = plan.devices + " устройства";
    $("shop-total").textContent = money(plan.priceRub);
    if (history.replaceState) history.replaceState(null, "", "?plan=" + encodeURIComponent(id));
    state.testOrder = null;
    $("shop-test-simulate").hidden = true;
    $("shop-test-refresh").hidden = true;
    $("shop-test-activation").hidden = true;
    $("shop-test-email").hidden = true;
    $("shop-test-link").hidden = true;
    $("shop-test-link").removeAttribute("href");
    testMessage("");
  }
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
      note.textContent = "На " + plan.days + " дней";
      button.append(title, subtitle, price, note);
      button.addEventListener("click", () => select(plan.id));
      cards.append(button);
    }
    const requested = new URLSearchParams(location.search).get("plan");
    select(state.plans.some(p => p.id === requested) ? requested : "30");
    $("shop-buy").disabled = !state.config?.checkout_ready;
    $("shop-buy").textContent = state.config?.checkout_ready ? "Перейти к оплате ↗" : "Оплата пока недоступна";
    $("shop-test-create").disabled = !state.config?.sandbox_available;
  }
  async function load() {
    try {
      const [plans, config] = await Promise.all([
        api("/api/shop/plans"), api("/api/shop/config")
      ]);
      if (!Array.isArray(plans.items) || !plans.items.length) throw Error("Каталог пуст");
      state.plans = plans.items;
      state.config = config;
      draw();
      message(config.checkout_ready
        ? "Оплата включена для авторизованных покупателей."
        : "Реальные платежи временно отключены. Сайт и цены доступны, интеграция тестируется без списаний.");
      if (!config.sandbox_available) {
        testMessage("Sandbox отключён на сервере. Для теста требуется включить режим и задать секретный токен.");
      }
    } catch (err) {
      message("Не удалось загрузить каталог или настройки: " + (err.message || "Ошибка сети"));
      $("shop-buy").disabled = true;
      $("shop-test-create").disabled = true;
    }
  }
  $("shop-buy").addEventListener("click", async () => {
    if (state.busy || !state.config?.checkout_ready || !state.selected) return;
    state.busy = true;
    $("shop-buy").disabled = true;
    try {
      // Reuse the same server-side intent if network timeouts or repeated
      // clicks occur: never create a second invoice for an uncertain request.
      if(!globalThis.crypto || !crypto.randomUUID){
        throw Error("Для защищённой оплаты нужен современный браузер с HTTPS.");
      }
      const intentName = "vainah-live-checkout-intent-v1-" + state.selected.id;
      let checkoutKey = sessionStorage.getItem(intentName);
      if(!checkoutKey){
        checkoutKey = crypto.randomUUID();
        sessionStorage.setItem(intentName, checkoutKey);
      }
      const reply = await api("/api/shop/checkout", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": checkoutKey
        },
        body: JSON.stringify({plan: state.selected.id})
      });
      const url = new URL(reply.pay_url);
      if (url.protocol !== "https:" || url.host !== "pay.rollypay.io" ||
          !/^\/pay\/[A-Za-z0-9_-]{6,255}\/?$/.test(url.pathname) ||
          url.search || url.hash) throw Error("Недопустимый адрес платёжной формы");
      location.assign(url.href);
    } catch (err) {
      message("Оплата не запущена: " + (err.message || "Неизвестная ошибка"));
    } finally {
      state.busy = false;
      $("shop-buy").disabled = !state.config?.checkout_ready;
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
          : fulfillment.status === "ready_for_review"
            ? "Подтверждён webhook. План подготовлен к проверке оператором."
            : "Выдача заблокирована: " + (fulfillment.reason || "нет подтверждения");
      testMessage((issued ? "Тестовая автовыдача VPN подтверждена" :
          "План выдачи VPN — только демо") +
        "\nЗаказ: " + info.order_id +
        "\nСтатус оплаты: " + info.payment_status +
        "\nПодписанный webhook: " + (fulfillment.signed_webhook_received ? "да" : "нет") +
        "\nАккаунт привязан: " + (fulfillment.customer_identity_bound ? "да" : "нет") +
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
  load();
})();
