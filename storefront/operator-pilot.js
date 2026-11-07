/* Standalone first-party operator page. No third-party scripts, storage, or logs. */
(() => {
  "use strict";
  const el = id => document.getElementById(id);
  const operatorField = el("operator-token");
  const pilotField = el("pilot-token");
  const checkButton = el("check-button");
  const createButton = el("create-button");
  const discountButton = el("discount-button");
  const discountStatus = el("discount-status");
  const statusEl = el("pilot-status");
  const checkoutEl = el("checkout-result");
  const accountEl = el("account-status");
  let accountReady = false;
  let checkPassed = false;
  let discountReady = false;
  let attempted = false;
  let busy = false;

  function setMessage(element, message) {
    element.textContent = message;
  }
  function refreshButtons() {
    checkButton.disabled = busy;
    createButton.disabled = busy || attempted || !accountReady || !checkPassed;
    discountButton.disabled = busy || attempted || !accountReady || !discountReady;
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
  async function fetchDiscountStatus(headers) {
    const response = await fetch("/api/shop/operator/live-pilot/discount-status", {
      method: "GET", headers, credentials: "same-origin", cache: "no-store"
    });
    const body = await readJson(response);
    if (!response.ok) throw new Error(safeError(response, body));
    return body;
  }
  function describeDiscount(state) {
    const count = Number.isInteger(state.discount_order_count)
      ? state.discount_order_count : (state.discount_order_exists ? 1 : 0);
    const remaining = Number.isInteger(state.discount_remaining)
      ? state.discount_remaining : Math.max(0, 2 - count);
    const progress = "Тестовые счета 10 ₽: " + count +
      " из 2. Осталось: " + remaining + ".\n";
    if (state.discount_checkout_ready === true) {
      return progress + (count === 0
        ? "RollyPay подтвердил закрытие счёта на 99 ₽.\n"
        : "Предыдущий тестовый заказ оплачен и выдан либо истёк/отменён.\n") +
        "Можно создать ещё один счёт на 10 ₽ за 1 день.";
    }
    const reasons = {
      DISCOUNT_PILOT_DISABLED: "Тестовый пилот пока отключён.",
      ORIGINAL_PILOT_UNVERIFIED: "Первый счёт на 99 ₽ ещё не подтверждён как закрытый.",
      ORIGINAL_PILOT_STILL_ACTIVE: "Счёт на 99 ₽ пока активен у RollyPay.",
      ORIGINAL_PROVIDER_UNAVAILABLE: "Не удалось проверить первый счёт у RollyPay.",
      ORIGINAL_PROVIDER_MISMATCH: "Данные первого счёта не совпали с RollyPay.",
      DISCOUNT_PILOT_LIMIT_REACHED: "Лимит двух тестовых счетов исчерпан.",
      DISCOUNT_PILOT_UNVERIFIED: "Предыдущий тестовый заказ ещё не закрыт.",
      DISCOUNT_PILOT_STILL_ACTIVE: "Предыдущий счёт на 10 ₽ ещё ожидает оплаты или выдачи.",
      DISCOUNT_PROVIDER_UNAVAILABLE: "Не удалось получить статус тестового счёта от RollyPay.",
      DISCOUNT_PROVIDER_MISMATCH: "Данные предыдущего тестового счёта не совпали.",
      LIVE_PILOT_STATUS_UNAVAILABLE: "Временная ошибка проверки заказов."
    };
    let message = progress + (reasons[state.reason] ||
      "Следующий счёт пока создавать нельзя.");
    if (count > 0) {
      message += "\nПоследняя оплата: " + (state.discount_payment_state || "unknown") +
        "\nВыдача VPN: " + (state.discount_delivery_state || "unknown");
      if (state.discount_access_email_sent) {
        message += "\nПисьмо с доступом отправлено.";
      }
    }
    return message;
  }
  function describeStatus(state) {
    const orderExists = state.pilot_order_exists === true;
    const messages = [
      "Проверка выполнена.",
      "Обработка подписанного платежа: " +
        (state.pilot_processing_enabled === true ? "доступна" : "заблокирована"),
      "Создание исходного счёта на 99 ₽: " +
        (state.pilot_checkout_ready === true ? "доступно" : "недоступно")
    ];
    if (orderExists) {
      messages.push("Первый счёт на 99 ₽ уже существует. Тестовые счета на 10 ₽ проверяются ниже.");
      if (state.payment_state) messages.push("Состояние оплаты: " + state.payment_state);
      if (state.delivery_state) messages.push("Выдача VPN: " + state.delivery_state);
      if (state.access_email_sent === true) messages.push("Письмо с доступом отправлено.");
    }
    return messages.join("\n");
  }
  async function checkStatus() {
    checkPassed = false;
    discountReady = false;
    busy = true;
    refreshButtons();
    try {
      await loadAccount();
      const headers = credentialHeaders();
      const state = await fetchStatus(headers);
      setMessage(statusEl, describeStatus(state));
      checkPassed = state.pilot_checkout_ready === true &&
        state.pilot_order_exists === false;
      if (checkPassed && !accountReady) {
        setMessage(checkoutEl, "Пилот готов, но сначала войди через подтверждённую почту.");
      } else if (checkPassed) {
        setMessage(checkoutEl, "Пилот готов. Первый счёт ещё не создан.");
      } else {
        setMessage(checkoutEl, "Новый счёт на 99 ₽ создавать нельзя. Проверь статус существующего заказа.");
      }
      try {
        const discount = await fetchDiscountStatus(headers);
        discountReady = discount.discount_checkout_ready === true;
        setMessage(discountStatus, describeDiscount(discount));
      } catch (error) {
        discountReady = false;
        setMessage(discountStatus, "Проверка 10 ₽ недоступна: " + error.message);
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

  async function createDiscountInvoice() {
    if (!discountReady || !accountReady || attempted || busy) return;
    if (!window.confirm(
      "Создать следующий НАСТОЯЩИЙ тестовый счёт на 10 ₽ за VPN на 1 день? " +
      "Если RollyPay отклонит сумму или запрос прервётся, не повторяй его."
    )) return;
    attempted = true;
    discountReady = false;
    checkPassed = false;
    busy = true;
    refreshButtons();
    setMessage(discountStatus, "Проверяем окончательное закрытие предыдущего счёта.");
    try {
      const headers = credentialHeaders();
      const state = await fetchDiscountStatus(headers);
      if (state.discount_checkout_ready !== true) {
        setMessage(discountStatus, describeDiscount(state));
        return;
      }
      const response = await fetch(
        "/api/shop/operator/live-pilot/discount-checkout", {
          method: "POST",
          headers: {
            ...headers, "Content-Type": "application/json",
            "Idempotency-Key": crypto.randomUUID()
          },
          credentials: "same-origin", cache: "no-store",
          body: JSON.stringify({plan: "pilot-1d"})
        }
      );
      const body = await readJson(response);
      if (!response.ok) {
        setMessage(discountStatus, "Создание не подтверждено: " +
          safeError(response, body) +
          ". Не повторяй запрос: проверь статус через оператора.");
        return;
      }
      let target;
      try { target = new URL(body.pay_url); } catch { target = null; }
      if (!target || target.protocol !== "https:" ||
          target.hostname !== "pay.rollypay.io" ||
          target.username || target.password || target.port) {
        setMessage(discountStatus,
          "Ссылка оплаты не прошла проверку. Не повторяй запрос.");
        return;
      }
      setMessage(discountStatus, "Счёт на 10 ₽ создан. Открывается RollyPay.");
      clearTokens();
      window.location.assign(target.href);
    } catch {
      setMessage(discountStatus,
        "Результат неизвестен. Не повторяй запрос — проверь статус заказа.");
    } finally {
      busy = false;
      clearTokens();
      refreshButtons();
    }
  }

  checkButton.addEventListener("click", checkStatus);
  discountButton.addEventListener("click", createDiscountInvoice);
  createButton.addEventListener("click", createInvoice);
  window.addEventListener("pagehide", clearTokens);
  void loadAccount();
})();
