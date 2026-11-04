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
    if(message === "PROVIDER_SANDBOX_NOT_CONFIRMED") return "RollyPay не подтвердил тестовый режим. Создание счёта остановлено без перехода к оплате.";
    if(message === "PROVIDER_TIMEOUT") return "Истекло время ожидания ответа RollyPay.";
    if(message === "PROVIDER_NETWORK") return "Ошибка соединения с API RollyPay.";
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
    state.testOrder = order;
    $("shop-test-resume").value = order.order_id;
    $("shop-test-simulate").hidden = order.mode !== "mock" || order.status !== "created";
    $("shop-test-refresh").hidden = order.mode !== "provider";
    $("shop-test-activation").hidden = false;
    testMessage("Тестовый заказ: " + order.order_id +
      "\nСтатус: " + order.status + "\nСумма: " + order.amount_rub +
      " ₽\nТестовый режим, VPN не выдан.");
  }
  function select(id) {
    const plan = state.plans.find(p => p.id === id);
    if (!plan) return;
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
      const reply = await api("/api/shop/checkout", {
        method: "POST", headers: {"Content-Type": "application/json"},
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
        testMessage("Связь с API RollyPay подтверждена (чтение тестовых платежей). " +
          "Это ещё не подтверждает возможность создать тестовый счёт.");
      }else{
        testMessage("Доступ к RollyPay не проверен: " + explainProviderError(result.reason));
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
      rows.push("Доставка webhook: ещё не подтверждена этой проверкой");
      rows.push("Автоматическая выдача VPN: отключена");
      testMessage(rows.join(String.fromCharCode(10)));
    } catch (err) {
      testMessage("Проверка webhook: " + explainProviderError(err.message));
    } finally {
      state.busy = false;
      $("shop-test-webhook").disabled = false;
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
        testMessage("Тестовый счёт создан. Переходим на защищённый сайт RollyPay…");
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
      testMessage("План выдачи VPN — только демо\nЗаказ: " + info.order_id +
        "\nСтатус оплаты: " + info.payment_status +
        "\nПериод: " + info.duration_days + " дней" +
        "\nУстройств: " + info.device_limit +
        "\nH1Cloud подключён: нет\nVPN выдан: нет\n" + info.message);
    }catch(err){
      testMessage("План выдачи VPN не готов: " + explainProviderError(err.message));
    }finally{
      state.busy = false;
    }
  });
  load();
})();
