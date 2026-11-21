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
  let currentUrl = null;
  let busy = false;
  const messages = {
    eligible: "Можно активировать пробный доступ. Нужна только подтверждённая почта.",
    claimed: "Запрос принят, проверяется H1Cloud. Повторный запрос не создаст второй пробник.",
    manual_review: "Активация требует проверки оператором. Не повторяй заявку — напиши в поддержку.",
    delivered: "Пробная VPN-подписка выдана. Используй кнопку копирования ниже."
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
  function showLink(data) {
    currentUrl = safeUrl(data.subscription_url);
    linkBox.hidden = !currentUrl;
    if (currentUrl) {
      open.href = currentUrl;
      open.referrerPolicy = "no-referrer";
      const date = Date.parse(data.expires_at);
      byId("trial-expiry").textContent = Number.isNaN(date)
        ? "Действует 24 часа после выдачи."
        : "Срок действия: " + new Date(date).toLocaleString("ru-RU");
    } else {
      open.removeAttribute("href");
    }
  }
  async function refresh() {
    if (busy) return;
    busy = true;
    claim.disabled = true;
    currentUrl = null;
    linkBox.hidden = true;
    status.textContent = "Проверяем статус пробного доступа…";
    try {
      const config = await request("/api/trial/config");
      const auth = await request("/api/email-auth/account");
      if (!auth.authenticated || !auth.user?.email) {
        login.hidden = false;
        status.textContent = "Войди по email и подтверди его кодом, чтобы получить пробный VPN.";
        claim.textContent = "Сначала войди";
        return;
      }
      login.hidden = true;
      const state = await request("/api/trial/status");
      status.textContent = messages[state.status] ||
        "Статус: " + String(state.status || "неизвестен");
      if (state.status === "eligible" && state.can_claim === true &&
          config.available === true) {
        claim.disabled = false;
        claim.textContent = "Активировать бесплатно";
      } else if (state.status === "eligible") {
        claim.textContent = "Пробник временно недоступен";
        status.textContent = "Новые пробные подключения пока не включены. Платные тарифы работают отдельно.";
      } else {
        claim.textContent = "Пробный доступ уже использован";
        if (state.status === "delivered") showLink(state);
      }
    } catch (error) {
      claim.textContent = "Проверка недоступна";
      status.textContent = "Не удалось проверить пробник. Повтори позже: " +
        (error.status === 401 ? "войти в аккаунт." : "сервер временно недоступен.");
    } finally {
      busy = false;
    }
  }
  claim.addEventListener("click", async () => {
    if (busy || claim.disabled) return;
    busy = true;
    claim.disabled = true;
    status.textContent = "Проверяем параметры VPN на H1Cloud. Не отправляй повторную заявку.";
    try {
      const data = await request("/api/trial/claim", {method: "POST", headers: {"Content-Type": "application/json"}});
      status.textContent = "Готово! Пробный VPN активирован на 24 часа, 2 устройства и 10 ГБ.";
      claim.textContent = "Пробник активирован";
      showLink(data);
    } catch (error) {
      status.textContent = error.status === 409
        ? "Пробник уже использован или доступен только новым клиентам. Обнови статус."
        : error.status === 429
          ? "Сегодня закончился лимит новых пробных подключений. Попробуй позднее."
          : "Активация не подтверждена. Возможно, нужна ручная проверка H1Cloud. Не нажимай повторно — напиши в поддержку.";
      claim.textContent = "Проверить статус";
    } finally { busy = false; }
  });
  byId("refresh").addEventListener("click", refresh);
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