/* Pure local recommendations; no network requests, account identifiers or VPN secrets. */
((scope) => {
  'use strict';
  const SYMPTOMS = Object.freeze([
    'cannot_connect','slow','import','no_internet','payment','disconnect'
  ]);
  const PLATFORMS = Object.freeze(['android','windows','macos','ios','other']);
  const LABELS = Object.freeze({
    android:'Android',windows:'Windows',macos:'macOS',ios:'iOS / iPadOS',other:'Другое устройство'
  });
  const TITLES = Object.freeze({
    cannot_connect:'VPN не подключается',
    slow:'Медленное соединение',
    import:'Ошибка импорта подписки',
    no_internet:'Пропадает интернет',
    payment:'Оплачено, но доступ не появился',
    disconnect:'VPN отключается сам',
  });
  const ACCOUNTS = new Set([
    'paid_profile_active','no_confirmed_delivery','paid_profile_not_active',
    'provider_unverified','account_state_unverified','not_checked','unavailable'
  ]);
  const add = (list, value) => { if (!list.includes(value)) list.push(value); };
  function evaluate({symptom,platform,account,infra,site,online} = {}) {
    if (!SYMPTOMS.includes(symptom) || !PLATFORMS.includes(platform))
      throw new Error('UNKNOWN_DIAGNOSTIC_SELECTION');
    const status = ACCOUNTS.has(account) ? account : 'not_checked';
    const steps = [], facts = [];
    let priority = 'information';
    add(facts, 'Проверка VPN-туннеля и отдельных серверов с этого сайта невозможна.');
    if (online === false) {
      add(steps,'Браузер сообщает об отсутствии сети. Проверь Wi-Fi или мобильный интернет без VPN, затем повтори диагностику.');
      add(facts,'navigator.onLine — подсказка браузера, а не подтверждённая проверка интернета.');
      priority = 'attention';
    }
    if (infra === 'attention') {
      add(steps,'Служебный API сообщил об ошибке. Проверь страницу статуса и повтори позже; это не доказывает сбой всех VPN-серверов.');
      priority = 'attention';
    } else if (infra === 'unknown') {
      add(facts,'Не удалось подтвердить доступность служебных API.');
    }
    if (status === 'paid_profile_not_active') {
      add(steps,'Оплаченный заказ обнаружен, но H1Cloud не подтвердил активный профиль. Обратись в поддержку с номером заказа из кабинета. Не оплачивай повторно.');
      priority = 'attention';
    } else if (status === 'no_confirmed_delivery') {
      add(steps,'В этом аккаунте не найдена подтверждённая выданная подписка. Проверь, под каким email или Telegram входил при оплате. Не создавай второй платёж для проверки.');
      priority = 'attention';
    } else if (status === 'provider_unverified' || status === 'account_state_unverified') {
      add(steps,'Состояние подписки нельзя полностью подтвердить сейчас. Обнови кабинет позже; неизвестный статус не означает завершение срока.');
    } else if (status === 'not_checked') {
      add(steps,'Войди в личный кабинет с подтверждённой почтой, затем запусти проверку подписки.');
    } else if (status === 'unavailable') {
      add(steps,'Личную подписку проверить не удалось. Убедись, что вошёл в свой аккаунт, или повтори позднее.');
    } else if (status === 'paid_profile_active') {
      add(facts,'H1Cloud подтвердил активный оплаченный профиль. Работа VPN на устройстве отдельно не проверена.');
    }

    switch (symptom) {
      case 'cannot_connect':
        add(steps,'Убедись, что на устройстве есть доступ в интернет без VPN. Затем перезапусти VPN-клиент и повтори подключение.');
        add(steps,'Открой личный кабинет, обнови подписку в приложении и проверь выбранную локацию, если клиент позволяет её выбирать.');
        break;
      case 'slow':
        add(steps,'Сравни качество Wi-Fi и мобильной сети. Не измеряй скорость через сайт как скорость конкретного VPN-сервера.');
        add(steps,'Если клиент предлагает реальные измерения задержки серверов, выбирай локацию по ним. Сайт пока таких метрик не получает.');
        break;
      case 'import':
        add(steps,'Скопируй личную ссылку ещё раз из своего кабинета; не публикуй её в чате поддержки.');
        add(steps,'Проверь, что VPN-клиент поддерживает нужный формат подписки и VLESS/Reality. Если импорт по ссылке не работает, проверь доступный в кабинете альтернативный способ.');
        break;
      case 'no_internet':
        add(steps,'Отключи VPN на короткое время и проверь доступ к обычным сайтам. Если интернет не появился, проблема может быть в исходной сети.');
        add(steps,'Убедись, что DNS и системные настройки VPN не конфликтуют с другим VPN-клиентом.');
        break;
      case 'payment':
        add(steps,'Проверь статус заказа в кабинете под тем же аккаунтом, через который была оплата.');
        add(steps,'Если оплата подтверждена, но VPN не выдан, сообщи номер заказа в поддержку. Не оплачивай второй раз.');
        break;
      case 'disconnect':
        add(steps,'Проверь переход между Wi-Fi и мобильной сетью, а также ограничения фоновой работы VPN-приложения.');
        add(steps,'Если приложение предлагает автоподключение, проверь его настройку. Kill Switch должен работать в VPN-приложении или настройках ОС, не на сайте.');
        break;
    }
    if (platform === 'android') {
      add(steps,'Android: проверь разрешение VPN и ограничения энергосбережения для VPN-приложения. Режим «Всегда включён VPN» настраивается в системных параметрах VPN.');
    } else if (platform === 'windows') {
      add(steps,'Windows: проверь разрешения приложения и отсутствие конфликта с другим VPN-клиентом. При ошибке импорта используй поддерживаемый формат конфигурации.');
    } else if (platform === 'macos') {
      add(steps,'macOS: проверь разрешение сетевого расширения и системный список VPN-подключений.');
    } else if (platform === 'ios') {
      add(steps,'iOS/iPadOS: проверь разрешение добавления VPN-конфигурации в настройках и наличие совместимого VPN-клиента.');
    }
    if (site && Number.isFinite(site.median) && site.samples >= 2) {
      add(facts,'Время ответа сайта Render: медиана ' + Math.round(site.median) +
        ' мс по ' + site.samples + ' запросам. Это НЕ пинг VPN-сервера.');
    } else {
      add(facts,'Надёжный замер задержки до сайта не получен; VPN-задержка неизвестна.');
    }
    return Object.freeze({
      symptom, platform, title: TITLES[symptom],
      platform_label: LABELS[platform], priority,
      account_result: status, steps, facts,
      server_recommendation: null, tunnel_verified: false,
      suggested_links: ['/account.html','/status.html','/support-center.html']
    });
  }
  const api = Object.freeze({evaluate, SYMPTOMS, PLATFORMS});
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (scope) scope.VainahDiagnosticRules = api;
})(typeof window === 'undefined' ? null : window);
