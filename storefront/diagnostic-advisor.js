/* Vainah Check 2.0: browser-only diagnosis, redacted report, real site probes. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const rules = window.VainahDiagnosticRules;
  const run = $('advisor-run'), copy = $('advisor-copy'), result = $('advisor-result');
  const progress = $('advisor-progress');
  if (!rules || !run || !copy || !result || !progress) return;

  const node = (name, content, css = '') => {
    const element = document.createElement(name);
    element.textContent = content;
    if (css) element.className = css;
    return element;
  };
  const summary = {text: null};
  let active = false;
  const fetchJson = async (path, authenticated) => {
    const response = await fetch(path, {
      method: 'GET', cache: 'no-store',
      credentials: authenticated ? 'same-origin' : 'omit',
      headers: {Accept: 'application/json'},
      signal: AbortSignal.timeout(12000),
    });
    if (!response.ok) throw new Error('HTTP_' + response.status);
    return response.json();
  };
  const pingOnce = async () => {
    const started = performance.now();
    const response = await fetch('/api/speedtest/ping', {
      method: 'GET', cache: 'no-store', credentials: 'omit',
      signal: AbortSignal.timeout(8000),
    });
    if (response.status === 429) throw new Error('HTTP_429');
    if (response.status !== 204) throw new Error('PROBE_FAILED');
    return Math.round(performance.now() - started);
  };
  async function browserEvidence() {
    const samples = [];
    let rateLimited = false;
    for (let index = 0; index < 3; index++) {
      try {
        samples.push(await pingOnce());
      } catch (error) {
        rateLimited = String(error.message).includes('429');
        if (rateLimited) break;
      }
    }
    if (samples.length < 2) return null;
    samples.sort((a, b) => a - b);
    return {
      samples: samples.length,
      median: samples[Math.floor(samples.length / 2)],
      spread: samples[samples.length - 1] - samples[0],
    };
  }
  const allowedAccount = new Set([
    'paid_profile_active','no_confirmed_delivery','paid_profile_not_active',
    'provider_unverified','account_state_unverified'
  ]);
  const allowedInfra = new Set(['attention','partial','control_plane_checks_ok']);
  const format = (diagnosis, facts, measured) => {
    const lines = [
      'Vainah Check — обезличенный диагностический отчёт',
      'Проблема: ' + diagnosis.title,
      'Платформа: ' + diagnosis.platform_label,
      'Проверка подписки: ' + diagnosis.account_result,
      'Состояние API: ' + facts.infra,
      'Сайт Render (медиана): ' + (measured ? Math.round(measured.median) +
          ' мс (' + measured.samples + ' запроса)' : 'нет измерений'),
      'VPN-туннель: не проверялся',
      'Отдельные VPN-серверы: не измерялись',
      '',
      'Рекомендации:',
      ...diagnosis.steps.map((step, i) => String(i + 1) + '. ' + step),
      '',
      'Отчёт не содержит VPN-ключи, email, токены или сведения о заказах.',
    ];
    return lines.join('\n');
  };
  async function diagnose() {
    if (active) return;
    const symptom = $('advisor-symptom').value;
    const platform = $('advisor-platform').value;
    if (!rules.SYMPTOMS.includes(symptom) || !rules.PLATFORMS.includes(platform)) {
      progress.textContent = 'Выбери проблему и устройство.';
      return;
    }
    active = true; run.disabled = true; copy.disabled = true;
    summary.text = null;
    result.replaceChildren(node('p','Проверяем доступность сервиса…','empty'));
    progress.textContent = 'Проверяем API, подписку в этом аккаунте и время ответа сайта…';
    try {
      const [apiStatus, accountStatus, site] = await Promise.all([
        fetchJson('/api/site/check/summary', false)
          .then(x => x.summary).catch(() => 'unknown'),
        fetchJson('/api/account/connection-check', true)
          .then(x => x.result).catch(() => 'unavailable'),
        browserEvidence().catch(() => null),
      ]);
      const infra = allowedInfra.has(apiStatus) ? apiStatus : 'unknown';
      const account = allowedAccount.has(accountStatus) ? accountStatus :
        'unavailable';
      const online = typeof navigator.onLine === 'boolean' ? navigator.onLine : null;
      const diagnosis = rules.evaluate({
        symptom, platform, account, infra, site, online,
      });
      result.replaceChildren();
      const heading = node('h3',diagnosis.title+' · '+diagnosis.platform_label);
      const facts = node('div','','advisor-facts');
      for (const text of diagnosis.facts) facts.append(node('p',text,'small'));
      const steps = node('ol','','advisor-steps');
      for (const text of diagnosis.steps) steps.append(node('li',text));
      result.append(heading,facts,node('h4','Что проверить по порядку'),steps);
      summary.text = format(diagnosis,{infra},site);
      copy.disabled = false;
      progress.textContent =
        'Готово. Рекомендации основаны на доступных фактах, но не являются тестом VPN-туннеля.';
    } catch {
      result.replaceChildren(node('p','Не удалось завершить проверку. Попробуй позже.','empty'));
      progress.textContent = 'Не удалось собрать диагностический отчёт.';
    } finally {
      active = false;run.disabled = false;
    }
  }
  run.addEventListener('click',() => void diagnose());
  copy.addEventListener('click',async () => {
    if (!summary.text) return;
    try {
      await navigator.clipboard.writeText(summary.text);
      progress.textContent = 'Обезличенный отчёт скопирован. Его можно вставить в обращение поддержки.';
    } catch {
      progress.textContent = 'Браузер не разрешил копирование. Результаты остаются на экране.';
    }
  });
})();
