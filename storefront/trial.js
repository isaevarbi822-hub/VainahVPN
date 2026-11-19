/* Client-side trial activation, server controls eligibility and quota. */
(() => {
  "use strict";
  const byId = id => document.getElementById(id);
  const claim = byId("claim");
  const status = byId("trial-status");
  const login = byId("login");
  const linkBox = byId("trial-link-box");
  const copy = byId("copy");
  const open = byId("open");
  const refreshButton = byId("refresh");
  let currentUrl = null;
  let busy = false;
  const messages = {
    eligible: "Можно активировать пробный доступ. Нужна только подтверждённая почта.",
    claimed: "Запрос принят, проверяется H1Cloud. Повторный запрос не создаст второй пробник.",
    manual_review: "Активация требует проверки оператором. Обратись в поддержку.",
    expired: "Срок пробной подписки закончился. Выбери тариф, чтобы продолжить пользоваться VPN.",
    paid_customer: "Пробный доступ доступен новым клиентам. Активные подписки находятся в личном кабинете."
  };
  async function request(path, options = {}) {
    const ctrl = new AbortController();
    const id = setTimeout(() => ctrl.abort(), 13000);
    try {
      const response = await fetch(path, {
        cache: "no-store", credentials: "same-origin",
        signal: ctrl.signal, ...options
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = typeof result.detail === "string" ? result.detail : "";
        const error = new Error(detail || "HTTP " + response.status);
        error.status = response.status;
        throw error;
      }
      return result;
    } finally {
      clearTimeout(id);
    }
  }
  function safeUrl(value) {
    if (typeof value !== "string") return null;
    try {
      const url = new URL(value);
      if (url.protocol !== "https:" || url.username || url.password || url.hash) return null;
      return url.href;
    } catch { return null; }
  }
  function clearLink() {
    currentUrl = null;
    linkBox.hidden = true;
    open.removeAttribute("href");
    byId("trial-expiry").textContent = "";
    copy.textContent = "Скопировать VPN-ссылку";
  }
  function showLink(data) {
    const url = safeUrl(data.subscription_url);
    const date = Date.parse(data.expires_at);
    if (!url || !Number.isFinite(date)) throw new Error("Invalid trial access response");
    currentUrl = url;
    open.href = url;
    byId("trial-expiry").textContent = "Срок действия: " + new Date(date).toLocaleString("ru-RU");
    linkBox.hidden = false;
  }
  function promptLogin() {
    login.hidden = false;
    status.textContent = "Войди по email и подтверди его кодом, чтобы получить пробный VPN.";
    claim.textContent = "Сначала войди";
  }
  function setBusy(value) {
    busy = value;
    refreshButton.disabled = value;
  }
  async function refresh() {
    if (busy) return;
    setBusy(true);
    claim.disabled = true;
    clearLink();
    status.textContent = "Проверяем статус пробного доступа…";
    try {
      const auth = await request("/api/email-auth/account");
      if (!auth.authenticated || !auth.user?.email) {
        promptLogin();
        return;
      }
      login.hidden = true;
      const state = await request("/api/trial/status");
      status.textContent = messages[state.status] ||
        "Статус: " + String(state.status || "неизвестен");
      if (state.status === "eligible" && state.can_claim === true) {
        claim.disabled = false;
        claim.textContent = "Активировать бесплатно";
      } else if (state.status === "eligible") {
        claim.textContent = "Пробник временно недоступен";
        status.textContent = "Новые пробные подключения пока не включены. Платные тарифы работают отдельно.";
      } else {
        const labels = {claimed: "Активация проверяется", manual_review: "Нужна проверка",
          delivered: "Пробник активирован", expired: "Пробник закончился",
          paid_customer: "Пробник для новых клиентов"};
        claim.textContent = labels[state.status] || "Активация недоступна";
        if (state.status === "delivered") {
          showLink(state);
          status.textContent = "Пробная VPN-подписка выдана. Используй кнопку копирования ниже.";
        }
      }
    } catch (error) {
      if (error.status === 401) promptLogin();
      else {
        claim.textContent = "Проверка недоступна";
        status.textContent = "Не удалось проверить пробник. Обнови статус чуть позже.";
      }
    } finally {
      setBusy(false);
    }
  }
  claim.addEventListener("click", async () => {
    if (busy || claim.disabled) return;
    setBusy(true);
    claim.disabled = true;
    status.textContent = "Проверяем параметры VPN на H1Cloud. Не отправляй повторную заявку.";
    try {
      const data = await request("/api/trial/claim", {method: "POST", headers: {"Content-Type": "application/json"}});
      if (data.status !== "delivered") throw new Error("Trial delivery unconfirmed");
      showLink(data);
      status.textContent = "Готово! Пробный VPN активирован на 24 часа, 2 устройства и 10 ГБ.";
      claim.textContent = "Пробник активирован";
    } catch (error) {
      if (error.status === 401) {
        promptLogin();
        return;
      }
      status.textContent = error.status === 409
        ? "Пробник уже использован или доступен только новым клиентам. Обнови статус."
        : error.status === 429
          ? "Сегодня закончился лимит новых пробных подключений. Попробуй позднее."
          : "Активация пока не подтверждена. Обнови статус и, если нужна проверка, обратись в поддержку.";
      claim.textContent = "Активация не подтверждена";
    } finally { setBusy(false); }
  });
  refreshButton.addEventListener("click", refresh);
  copy.addEventListener("click", async () => {
    if (!currentUrl) return;
    try {
      await navigator.clipboard.writeText(currentUrl);
      copy.textContent = "Ссылка скопирована";
    } catch {
      copy.textContent = "Не удалось скопировать";
    }
  });
  void refresh();
})();
