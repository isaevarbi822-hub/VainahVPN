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
      state.testOrder = created;
      testMessage("Тестовый заказ: " + created.order_id + "\nСтатус: " + created.status +
        "\nСумма: " + created.amount_rub + " ₽\nVPN не выдан, реального списания нет.");
      $("shop-test-simulate").hidden = created.mode !== "mock";
      $("shop-test-refresh").hidden = created.mode !== "provider";
      if (created.pay_url) {
        const url = new URL(created.pay_url);
        if (url.protocol !== "https:" || url.host !== "pay.rollypay.io" ||
            !/^\/pay\/[A-Za-z0-9_-]{6,255}\/?$/.test(url.pathname) || url.search || url.hash) {
          throw Error("Неверная тестовая ссылка от провайдера");
        }
        $("shop-test-link").href = url.href;
        $("shop-test-link").hidden = false;
      }
    } catch (err) { testMessage("Не удалось создать тестовый заказ: " + (err.message || "Ошибка сети")); }
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
      testMessage("RollyPay sandbox заказ: " + result.order_id +
        "\\nСтатус: " + result.status + "\\nСумма: " + result.amount_rub +
        " ₽\\nРеальных списаний нет, VPN не выдан.");
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
      testMessage("Симуляция завершена: " + reply.status +
        "\nЭто не настоящая оплата и не активная VPN-подписка.");
      $("shop-test-simulate").hidden = true;
    } catch (err) {testMessage("Ошибка симуляции: " + (err.message || "Ошибка сети"));}
    finally {state.busy = false;}
  });
  load();
})();
