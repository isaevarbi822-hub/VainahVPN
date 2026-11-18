# Platega рядом с RollyPay — 18 ноября 2026

Platega добавлена как отдельный вариант в `checkout.html`. RollyPay сохраняет
свои ключи, маршруты, sandbox, подарочные карты и операторские проверки.
Platega обслуживает покупку и продление обычных тарифов; подарочные карты пока
оформляются через прежнюю кассу RollyPay. Изменений APK для этого не требуется.

Код и тесты не включают кассу в работающем сервисе. Развёртывание и переменные
Render настраивает владелец. Реальную оплату в ходе разработки не проводили.

## Настройки Python backend в Render

Сначала развернуть проверенные изменения из PR в ветку, которую используют
сайт и Python backend (`feat/restore-site-rollypay-checkout`). Обновить сначала
backend, затем сайт. Не переключать
Render на старую Android-ветку. Миграция PostgreSQL выполняется под блокировкой
при первом обращении к заказам; существующие заказы получают `gateway=rollypay`.
Идентификаторы платежей и лимит одного пробного счёта разделены по кассам.

Добавить **только в Environment Python backend**, не в статический сайт/APK:

| Переменная | Значение |
| --- | --- |
| `PLATEGA_MERCHANT_ID` | Merchant ID (UUID) из настроек Platega |
| `PLATEGA_SECRET` | Выданный Platega секрет; не публиковать в чате/GitHub |
| `PLATEGA_MERCHANT_APPROVED` | `approved`, после подключения магазина провайдером |
| `PLATEGA_PILOT_ENABLED` | `enabled` для одной закрытой пробной покупки |
| `PLATEGA_CHECKOUT_ENABLED` | Сначала `disabled` |
| `PLATEGA_PAID_E2E_VERIFIED` | Сначала не задавать; это результат реальной проверки |
| `PUBLIC_SITE_ORIGIN` | `https://vainahvpn.onrender.com` |

Используются уже существующие `DATABASE_URL`, `SESSION_SIGNING_KEY`, рабочая
авторизация с подтверждённым email, почтовая доставка и настройки H1Cloud.
Не менять `SESSION_SIGNING_KEY`: он защищает существующие данные заказов.
Общие условия выдачи: `VAINAH_LIVE_CUSTOMER_ACCESS_ENABLED=enabled`,
`VAINAH_H1_WRITE_CONTRACT_APPROVED=approved`,
`VAINAH_LIVE_FULFILLMENT_APPROVED=approved`. Эти значения отражают уже
проверенную выдачу H1Cloud; наличие ключей само по себе её не подтверждает.

## Callback в кабинете Platega

Настройки → Callback URLs:

```text
https://vainahvpn-python-preview.onrender.com/api/shop/webhooks/platega
```

Использовать адрес **Python backend**, без редиректов и завершающего `/`.
Platega передаёт `X-MerchantId` и `X-Secret` в заголовках. Обработчик проверяет
их, затем сверяет транзакцию через API Platega: кассу, платёж, номер заказа,
исходную сумму и RUB. Возврат покупателя на сайт не подтверждает оплату.

Используется `POST https://app.platega.io/v2/transaction/process`: покупатель
выбирает доступный способ оплаты на странице Platega. После создания сервер
также проверяет заказ через `GET /transaction/{id}`. Указание метода оплаты
в клиентском запросе не требуется. Подтверждённый email и постоянный внутренний
идентификатор покупателя передаются в `metadata`; это отражено в Privacy.

## Одна пробная покупка перед публичным включением

1. Задать `VAINAH_LIVE_PILOT_EMAIL` — свой подтверждённый email;
   `VAINAH_LIVE_PILOT_OPERATOR_TOKEN` — отдельный секрет минимум 32 символа;
   `VAINAH_SANDBOX_TEST_TOKEN` — существующий операторский секрет минимум 24
   символа. Два токена должны отличаться. Обычные покупатели эти токены не получают.
2. Войти на сайте с этим email. Закрытый маршрут создания —
   `POST /api/shop/operator/platega/checkout`, JSON `{"plan":"30"}`.
   Передать cookie своего входа, `Origin: https://vainahvpn.onrender.com`,
   `Idempotency-Key` (один UUID v4), `X-Sandbox-Token`, `X-Live-Pilot-Token`.
   Создаётся **реальный** счёт на текущую серверную цену месячного тарифа
   (сейчас 149 ₽). Деньги списываются только при оплате на Platega.
3. Повторять запрос только с тем же UUID: вернётся тот же счёт. Если результат
   создания неизвестен, не менять UUID и не создавать ещё один счёт — сначала
   сверить заказ в кабинете Platega. Лимит — один пилотный заказ Platega.
4. Проверить оплату, приход callback, одну выдачу H1Cloud, доступ в кабинете и
   одно сервисное письмо. Безопасный статус:
   `GET /api/shop/operator/platega/status` с `X-Sandbox-Token`.
   Ожидаются `payment_state=paid`, `delivery_state=delivered`,
   `verified_webhook_received=true`, `h1_delivery_confirmed=true`,
   `access_email_sent=true`. Эти поля относятся только к пробному заказу Platega.
5. Повторно отправить callback из кабинета Platega. Срок и количество доступов
   не должны увеличиться повторно. Только после этого выставить
   `PLATEGA_PAID_E2E_VERIFIED=verified`, `PLATEGA_CHECKOUT_ENABLED=enabled` и
   общий `VAINAH_LIVE_CHECKOUT_ENABLED=enabled`; выключить
   `PLATEGA_PILOT_ENABLED`. Публичный `/api/shop/config` должен вернуть
   `gateways` с `platega.checkout_ready=true`.

Выключение `PLATEGA_CHECKOUT_ENABLED` закрывает новые продажи, но оставляет
обработку уже созданных платежей. Для них необходимо сохранить ключи и общие
условия выдачи. Повторы подтверждения используют существующий механизм
однократной выдачи H1Cloud и отправки письма. При неясном результате записи
H1Cloud автоматический повтор запрещён, заказ остаётся `manual_review`.

`DISPUTED`, `PARTIALLY_REFUNDED` и `CHARGEBACKED` требуют сверки оператором;
выданный доступ на H1Cloud автоматически не отзывается. Поздний `CONFIRMED`
не снимает `manual_review` и не отменяет chargeback/частичный возврат/отмену.
После исчерпания повторов Platega callback можно отправить вручную из кабинета.

## Проверки без настоящих платежей

```bash
cd backend
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check vainah tests
```

Для PostgreSQL-проверок задать `VAINAH_TEST_DATABASE_URL` отдельной тестовой БД.
Они создают и удаляют собственные схемы. Не использовать production database.
Проверяются независимые кассы, совпадающие ID разных провайдеров, повторный
callback, потерянный ответ создания, неверная сумма/валюта/заказ/авторизация,
пауза продаж, H1 и письмо однократно, выбор кассы и адреса переходов в браузере.

Официальные источники контракта: [авторизация](https://docs.platega.io/),
[создание счёта v2](https://docs.platega.io/создание-платежной-ссылки-без-заданного-метода-46297329e0),
[статус транзакции](https://docs.platega.io/проверка-статуса-оплаты-платежа-29203844e0),
[правила callback](https://docs.platega.io/колбэки-общая-информация-2499110m0).
