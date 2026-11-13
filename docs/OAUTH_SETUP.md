# Настройка входа Google и Telegram в Vainah VPN

Код OAuth уже реализован, но **без собственных Client ID и Client Secret от
провайдеров вход не активируется**. Никогда не отправляй секреты в чат, не
коммить их в GitHub и не вставляй их в HTML/JavaScript.

## 1. Google

1. Открой Google Cloud Console → Google Auth Platform / Credentials.
2. Настрой название приложения, контактную почту и аудиторию OAuth.
3. Создай **OAuth Client ID** типа **Web application**.
4. Укажи разрешённый адрес сайта:
   `https://vainahvpn-python-preview.onrender.com`
5. Укажи **Authorized redirect URI** (строго без завершающего слеша):
   `https://vainahvpn-python-preview.onrender.com/api/google/callback`
6. На Render → сервис Vainah VPN → Environment добавь:
   - `GOOGLE_CLIENT_ID` — Web client ID.
   - `GOOGLE_CLIENT_SECRET` — секрет Web OAuth-клиента.
7. После применения переменных открой `/api/google/config`. Должно быть
   `"available":true`. Затем проверь вход через
   `/account.html?login=google`.

Если OAuth-приложение Google в тестовом режиме, доступ будет только у
добавленных тестовых пользователей. Публикация и верификация настраиваются в
Google Cloud по правилам Google.

## 2. Современный Telegram Login (рекомендуется)

Старый iframe Login Widget — резервный вариант. Для нового OIDC:

1. Открой **@BotFather** в Telegram, выбери своего бота.
2. Открой раздел **Login Widget** (в новых настройках BotFather). Получи
   **Client ID** и **Client Secret**.
3. Добавь оба разрешённых адреса:
   - `https://vainahvpn-python-preview.onrender.com`
   - `https://vainahvpn-python-preview.onrender.com/api/telegram-oidc/callback`
4. Убедись, что алгоритм подписи ID-токенов — **RS256** (по умолчанию).
5. Добавь в Render Environment:
   - `TELEGRAM_OIDC_CLIENT_ID` — ID из BotFather.
   - `TELEGRAM_OIDC_CLIENT_SECRET` — OIDC Secret из BotFather.
6. После применения переменных открой `/api/telegram-oidc/config`.
   Должно быть `"available":true`.
7. Перейди на `/account.html?login=telegram` и нажми
   «Продолжить с Telegram». Откроется Telegram Authorization Code Flow;
   сервер проверяет подписанный ID-токен и выдаёт защищённую сессию.

**Не путай** `TELEGRAM_OIDC_CLIENT_SECRET` и `TELEGRAM_BOT_TOKEN`.
Последний нужен только для сохранённого старого режима входа и работы
бота. В старом виджете домен проверяется через `/setdomain` в BotFather.

## 3. Общие переменные

- `SESSION_SIGNING_KEY` — уже используемый секрет подписи сессий длиной
  не менее 32 символов. Не меняй его без необходимости: смена
  автоматически завершит текущие сессии.
- `PUBLIC_SITE_ORIGIN` —
  `https://vainahvpn-python-preview.onrender.com`.

**После смены домена** также обнови `PUBLIC_SITE_ORIGIN`, Authorized
Redirect URI Google и Allowed URLs Telegram. Иначе вход будет отклонён.

## Безопасность и данные

- Google использует OAuth 2.0 Authorization Code + PKCE + `state` + `nonce`;
  ID-токен проверяется по подписи Google, издателю и аудитории.
- Новый Telegram использует Authorization Code + PKCE + `state`,
  проверку JWKS и издателя Telegram. Сессия создаётся по подписанному
  Telegram ID, **а не по введённому пользователем ID**.
- Google-вход создаёт сессию подтверждённого email. Только эта почта
  получает доступ к связанным с ней заказам — чужие ключи не выдаются.
- Сессии используют HttpOnly, Secure, SameSite=Lax.
- Пароли Google/Telegram, токены доступа и секреты OAuth не попадают
  в HTML или локальное хранилище браузера.

Документация:
- https://developers.google.com/identity/protocols/oauth2/web-server
- https://core.telegram.org/bots/telegram-login
