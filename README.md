# Vainah VPN

**Новый репозиторий для переработанного Vainah VPN.**

> Статус: разработка. Это **не** готовая публичная версия VPN.
> Исходный Android-клиент ранее подключался с VLESS + REALITY, однако
> обновление HTTPS-подписки давало HTTP 403. Новая архитектура должна
> исправить диагностику и разделить компоненты, не выдавая успешную
> компиляцию за подтверждение работающего VPN.

## Цель

- **Android**: отдельный импорт подписок, локальное зашифрованное хранение,
  список серверов, управление подключением через libbox, счётчики трафика
  и реальная диагностика — без ложных надписей «Подключено».
- **Clerk**: нативная авторизация; никаких секретных ключей в APK.
- **Python/Render**: единый сервер для кабинета и подписок после полного
  переноса и тестирования. Не используем устаревший Netlify как
  необъявленную зависимость.
- **Оплата**: отключена до отдельной проверки RollyPay, базы, прав доступа,
  вебхуков и подтверждённой выдачи VPN.
- **iOS, Windows и macOS**: отдельные последующие этапы с платформенными
  VPN-движками; не имитируем работающие туннели.

## Правила разработки

1. Сохраняем работающие части libbox и подключение VLESS + REALITY.
2. Разделяем UI, сеть, хранилище и VPN-службу; не создаём монолитный экран.
3. Ссылка подписки и VLESS-ключ — секреты: не выводим их в логи, URL
   ошибок, публичные артефакты или аналитику.
4. HTTPS требует действительный сертификат; никаких обходов TLS.
5. HTTP 403 — отказ конкретному запросу, а не доказательство истечения
   подписки. Не копируем чужие идентификаторы устройства.
6. Изменения в продакшене — только после сборки, тестов и проверки на
   реальном устройстве. Существующий VainahVPN_bot остаётся нетронутым.

## Репозитории

- Новый проект: [VainahVPN](https://github.com/isaevarbi822-hub/VainahVPN).
- Исходная реализация для сверки, **не для прямого развёртывания**:
  [Vainahvpn_bot](https://github.com/isaevarbi822-hub/Vainahvpn_bot).

**Не публикуйте** токены H1Cloud, Clerk secret key, приватные ссылки
подписок и ключи RollyPay в GitHub, сообщениях или отчётах об ошибках.

## Unified development branch

The combined Android libbox client and Python/FastAPI cabinet live on
`feat/unified-android-python`. Review both workflows before merging.

- Android source: `android/`; test build via `.github/workflows/android.yml`.
- Python API: `backend/`; live dashboard routes in `web/`.
- Local run: `cd backend && pip install -e ".[dev]" && uvicorn vainah.main:app --reload`.
- Automated tests: `cd backend && python -m pytest -q`.
- Android libbox adapter is compiled only with `-PvainahEnableLibbox=true`.
- Python does not execute the Android VPN tunnel. Android VpnService/libbox does.
- Native Android real-device traffic, DNS, IPv6 and handover are unverified.
- Clerk/H1Cloud user APIs and RollyPay remain disabled in Python preview.

Never publish user subscription URLs, UUIDs, API tokens or live payment keys.
