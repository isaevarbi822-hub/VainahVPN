/* Standalone first-party operator page. No third-party scripts, storage, or logs. */
(() => {
  "use strict";
  const el = id => document.getElementById(id);
  const operatorField = el("operator-token");
  const pilotField = el("pilot-token");
  const checkButton = el("check-button");
  const createButton = el("create-button");
  const statusEl = el("pilot-status");
  const checkoutEl = el("checkout-result");
  const accountEl = el("account-status");
  let accountReady = false;
  let checkPassed = false;
  let attempted = false;
  let busy = false;

  function setMessage(element, message) {
    element.textContent = message;
  }
  function refreshButtons() {
    checkButton.disabled = busy;
    createButton.disabled = busy || attempted || !accountReady || !checkPassed;
  }
  function credentialHeaders() {
    const operator = operatorField.value.trim();
    const pilot = pilotField.value.trim();
    if (operator.length < 24 || pilot.length < 32 || operator === pilot) {
      throw new Error("Введи оба разных токена из Render.");
    }
    return {
      "X-Sandbox-Token": operator,
      "X-Live-Pilot-Token": pilot,
      "Accept": "application/json"
    };
  }
  function clearTokens() {
    operatorField.value = "";
    pilotField.value = "";
  }
  async function readJson(response) {
    try { return await response.json(); } catch { return {}; }
  }
  function safeError(response, body) {
    const code = body && typeof body.detail === "string" &&
      /^[A-Z][A-Z0-9_]{1,79}$/.test(body.detail)
      ? body.detail : "SERVER_UNAVAILABLE";
    return "HTTP " + response.status + ": " + code;
  }
  async function loadAccount() {
    try {
      const response = await fetch("/api/email-auth/account", {
        credentials: "same-origin", cache: "no-store"
      });
      const data = await readJson(response);
      accountReady = response.ok && data.authenticated === true &&
        typeof data.user?.email === "string";
      setMessage(accountEl, accountReady
        ? "Вход выполнен: " + data.user.email +
          ". Сервер отдельно проверит, разрешена ли эта почта для пилота."
        : "Сначала войди по коду из почты. Для пилота нужен подтверждённый email.");
    } catch {
      accountReady = false;
      setMessage(accountEl, "Не удалось проверить вход. Обнови страницу после авторизации.");
    }
    refreshButtons();
  }
  async function fetchStatus(headers) {
    const response = await fetch("/api/shop/operator/live-pilot/status", {
      method: "GET", headers, credentials: "same-origin", cache: "no-store"
    });
    const body = await readJson(response);
    if (!response.ok) throw new Error(safeError(response, body));
    return body;
  }
  function describeStatus(state) {
    const orderExists = state.pilot_order_exists === true;
    const messages = [
      "Проверка выполнена.",
      "Обработка подписанного платежа: " +
        (state.pilot_processing_enabled === true ? "доступна" : "заблокирована"),
      "Создание первого счёта: " +
        (state.pilot_checkout_ready === true ? "доступно" : "недоступно")
    ];
    if (orderExists) {
      messages.push("Пилотный заказ уже существует. Не создавай второй.");
      if (state.payment_state) messages.push("Состояние оплаты: " + state.payment_state);
      if (state.delivery_state) messages.push("Выдача VPN: " + state.delivery_state);
      if (state.access_email_sent === true) messages.push("Письмо с доступом отправлено.");
    }
    return messages.join("\n");
  }
  async function checkStatus() {
    checkPassed = false;
    busy = true;
    refreshButtons();
    try {
      await loadAccount();
      const state = await fetchStatus(credentialHeaders());
      setMessage(statusEl, describeStatus(state));
      checkPassed = state.pilot_checkout_ready === true &&
        state.pilot_order_exists === false;
      if (checkPassed && !accountReady) {
        setMessage(checkoutEl, "Пилот готов, но сначала войди через подтверждённую почту.");
      } else if (checkPassed) {
        setMessage(checkoutEl, "Пилот готов. Первый счёт ещё не создан.");
      } else {
        setMessage(checkoutEl, "Новый счёт создавать нельзя. Проверь статус уже существующего заказа.");
      }
    } catch (error) {
      setMessage(statusEl, "Проверка не прошла: " + error.message);
      setMessage(checkoutEl, "Создание счёта заблокировано.");
    } finally {
      busy = false;
      refreshButtons();
    }
  }

  async function createInvoice() {
    if (!checkPassed || !accountReady || attempted || busy) return;
    // No checkout POST until this specific user action and explicit confirmation.
    if (!window.confirm(
      "Создать ОДИН реальный счёт RollyPay на 99 ₽ за 30 дней? " +
      "Это НЕ Sandbox. После создания нельзя повторять запрос при ошибке."
    )) return;

    attempted = true;
    checkPassed = false;
    busy = true;
    refreshButtons();
    setMessage(checkoutEl, "Проверяем состояние перед единственным запросом.");
    try {
      const headers = credentialHeaders();
      const state = await fetchStatus(headers);
      if (state.pilot_checkout_ready !== true || state.pilot_order_exists === true) {
        setMessage(statusEl, describeStatus(state));
        setMessage(checkoutEl, "Заказ уже есть или пилот закрыт. Повторно создавать нельзя.");
        return;
      }
      // Generate once, immediately before the only POST. Never retry uncertain requests.
      const requestHeaders = {
        ...headers,
        "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID()
      };
      const response = await fetch("/api/shop/operator/live-pilot/checkout", {
        method: "POST", headers: requestHeaders,
        credentials: "same-origin", cache: "no-store",
        body: JSON.stringify({ plan: "30" })
      });
      const body = await readJson(response);
      if (!response.ok) {
        setMessage(checkoutEl,
          "Счёт не подтверждён: " + safeError(response, body) +
          ". Не повторяй запрос. Сначала проверь состояние заказа.");
        return;
      }
      let target;
      try { target = new URL(body.pay_url); } catch { target = null; }
      if (!target || target.protocol !== "https:" ||
          target.hostname !== "pay.rollypay.io" ||
          target.username || target.password || target.port) {
        setMessage(checkoutEl,
          "Ответ содержит неподтверждённую ссылку оплаты. Не повторяй запрос.");
        return;
      }
      setMessage(checkoutEl, "Счёт создан. Открываем защищённую страницу RollyPay.");
      clearTokens();
      window.location.assign(target.href);
    } catch {
      setMessage(checkoutEl,
        "Состояние создания счёта неизвестно. НЕ повторяй запрос: " +
        "проверяй статус заказа через операторский доступ.");
    } finally {
      busy = false;
      // On any checkout attempt, fields must be re-entered to inspect the result.
      clearTokens();
      refreshButtons();
    }
  }

  checkButton.addEventListener("click", checkStatus);
  createButton.addEventListener("click", createInvoice);
  window.addEventListener("pagehide", clearTokens);
  void loadAccount();
})();
