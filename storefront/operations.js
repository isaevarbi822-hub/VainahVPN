/* Read-only order monitoring. Secrets live only in input elements, never storage. */
(() => {
  "use strict";
  const el = id => document.getElementById(id);
  const button = el("ops-check");
  const status = el("ops-status");
  const root = el("ops-dashboard");
  const metrics = el("ops-metrics");
  const recent = el("ops-recent");
  const token = el("ops-sandbox");
  const pilot = el("ops-pilot");
  const exportButton = el("ops-export");
  let lastReport = null;
  const safe = value => String(value ?? "—");
  const indicators = [
    ["total_orders", "Заказов всего"],
    ["paid_delivered", "Оплачено и выдано"],
    ["paid_awaiting_delivery", "Оплачено: ожидает выдачи"],
    ["paid_claimed", "Выдача выполняется"],
    ["manual_review", "Требуют ручной проверки"],
    ["paid_delivered_email_not_sent", "Письмо ещё не отправлено"],
    ["unpaid_older_than_24h", "Неоплаченные старше 24 ч"],
    ["expiry_snapshot_48h", "Истекают в 48 ч (снимок H1)"],
    ["expiry_snapshot_7d", "Истекают в 7 дней (снимок H1)"],
    ["expiry_snapshot_past", "Снимок срока уже прошёл"],
  ];
  function draw(data) {
    lastReport = {
      checked_at: new Date().toISOString(),
      counters: indicators.map(([field, label]) => [
        label, Number.isInteger(data[field]) && data[field]>=0 ? data[field] : ""
      ])
    };
    exportButton.disabled = false;
    metrics.replaceChildren();
    for (const [field, label] of indicators) {
      const cell = document.createElement("div");
      cell.className = "metric";
      if (["manual_review", "paid_awaiting_delivery", "paid_delivered_email_not_sent"].includes(field)
          && Number(data[field]) > 0) cell.classList.add("attention");
      const value = document.createElement("strong");
      value.textContent = Number.isInteger(data[field]) ? String(data[field]) : "—";
      const text = document.createElement("small");
      text.textContent = label;
      cell.append(value, text);
      metrics.append(cell);
    }
    recent.replaceChildren();
    const orders = Array.isArray(data.recent) ? data.recent : [];
    for (const order of orders) {
      const tr = document.createElement("tr");
      const fields = [
        order.order_id, order.plan_id, order.payment_state, order.delivery_state,
        order.access_email_sent ? "Отправлено" : "Нет",
        order.created_at,
      ];
      for (const value of fields) {
        const td = document.createElement("td");
        td.textContent = safe(value);
        tr.append(td);
      }
      recent.append(tr);
    }
    if (!orders.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 6;td.textContent = "Заказов нет";tr.append(td);recent.append(tr);
    }
    el("ops-checked-at").textContent = "Проверено: " + new Date().toLocaleString("ru-RU") +
      ". Данные PostgreSQL на момент запроса, без фонового обновления.";
    root.hidden = false;
  }
  button.addEventListener("click", async () => {
    if (!token.value || !pilot.value) {
      status.textContent = "Заполни оба токена.";
      return;
    }
    button.disabled = true;
    lastReport = null;
    exportButton.disabled = true;
    root.hidden = true;
    status.textContent = "Читаем состояния заказов без изменения платежей…";
    try {
      const res = await fetch("/api/shop/operator/operations/summary", {
        headers: {"X-Sandbox-Token": token.value,
                  "X-Live-Pilot-Token": pilot.value},
        credentials: "same-origin", cache: "no-store"
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const errors = {
          401: "Нет входа по подтверждённой почте или неверен операторский токен.",
          403: "Почта не разрешена для оператора.",
          503: "Не удалось прочитать PostgreSQL."
        };
        throw new Error(errors[res.status] || "Сервер вернул HTTP " + res.status);
      }
      draw(data);
      status.textContent = "Состояние заказов получено. VPN и платежи не менялись.";
    } catch (error) {
      status.textContent = "Проверка недоступна: " + safe(error.message);
    } finally {
      button.disabled = false;
    }
  });
  exportButton.addEventListener("click", () => {
    if (!lastReport || !Array.isArray(lastReport.counters)) return;
    // Export only approved aggregate metrics, never order IDs or tokens.
    const rows = [["Показатель", "Количество"], ["Проверено (UTC)", lastReport.checked_at],
      ...lastReport.counters];
    const csv = "\uFEFF" + rows.map(row=>row.map(value=>
      '"' + String(value).replace(/"/g,'""') + '"').join(";")).join("\r\n") + "\r\n";
    const url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"}));
    const link=document.createElement("a");
    link.href=url;
    link.download="vainahvpn-orders-summary-"+lastReport.checked_at.slice(0,10)+".csv";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  el("ops-clear").addEventListener("click", () => {
    token.value = "";pilot.value = "";lastReport = null;
    exportButton.disabled = true;metrics.replaceChildren();recent.replaceChildren();
    root.hidden = true;status.textContent = "Токены очищены.";
  });
})();