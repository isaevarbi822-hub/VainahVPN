package app.vainah.vpn

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.text.InputType
import android.net.Uri
import androidx.browser.customtabs.CustomTabsIntent
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * Genuine native account, email OTP, free trial and tariff catalog.
 * Only selected PAYMENT is opened through the official website checkout.
 * The app never collects a bank card or triggers a payment on its own.
 */
class NativeCabinetActivity : Activity() {
    private val executor = Executors.newSingleThreadExecutor()
    private lateinit var api: NativeCabinetApi
    private var catalog: NativeCabinetCatalog.Snapshot? = null
    private var checkoutReady = false
    private var trialConfig: JSONObject? = null
    private var trialStatus: JSONObject? = null
    private var account: JSONObject? = null
    private var signedInEmail: String? = null
    private var telegramIdentity: String? = null
    private var googleAvailable = false
    private var telegramAvailable = false
    private var emailConfigured = true
    private var emailConfigKnown = false
    private var message: String? = null
    private var busy = false
    private var otpRequested = false
    private var pendingEmail = ""
    private var page = "cabinet"
    private var category = "all"
    private var shown = 12
    private var scroll: ScrollView? = null
    private var queuedOAuthCallback: Intent? = null

    private val ink = VainahDesign.ink
    private val muted = VainahDesign.muted
    private val violet = VainahDesign.purple

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        api = NativeCabinetApi(this)
        page = savedInstanceState?.getString("page")?.takeIf {
            it in setOf("cabinet", "plans")
        } ?: intent.getStringExtra("page")?.takeIf {
            it in setOf("cabinet", "plans")
        } ?: "cabinet"
        window.statusBarColor = VainahDesign.background
        window.navigationBarColor = VainahDesign.background
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility =
            View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
        render()
        if (!handleOAuthCallback(intent)) refresh()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (!handleOAuthCallback(intent)) refresh()
    }

    override fun onSaveInstanceState(out: Bundle) {
        out.putString("page", page)
        super.onSaveInstanceState(out)
    }

    override fun onDestroy() {
        executor.shutdownNow()
        super.onDestroy()
    }

    private fun beginSocialLogin(provider: String) {
        if (busy || provider !in setOf("google", "telegram")) return
        val enabled = if (provider == "google") googleAvailable else telegramAvailable
        if (!enabled) {
            message = "Этот способ входа пока не настроен на сервере VainahVPN."
            render()
            return
        }
        val verifier = NativeOAuthFlow.verifier()
        val challenge = NativeOAuthFlow.challenge(verifier)
        perform({
            api.post("/api/mobile-auth/start", JSONObject()
                .put("provider", provider).put("code_challenge", challenge))
        }) { outcome ->
            val result = outcome.getOrNull()
            val flow = result?.json?.optString("flow").orEmpty()
            val offered = result?.json?.optString("authorize_url").orEmpty()
            val expected = NativeCabinetCatalog.ORIGIN +
                (if (provider == "google") "/api/google/start?mobile_flow="
                else "/api/telegram-oidc/start?mobile_flow=") + flow
            if (result?.ok != true || !NativeOAuthFlow.validFlow(flow)
                || offered != expected) {
                message = when(result?.status) {
                    429 -> "Слишком много попыток входа. Повтори через 10 минут."
                    503 -> "Этот способ входа ещё не настроен на сервере."
                    403 -> "Проверь PUBLIC_SITE_ORIGIN в настройках сервера."
                    else -> "Не удалось открыть безопасный вход. Проверь подключение."
                }
                render()
                return@perform
            }
            api.saveOAuthPending(NativeOAuthFlow.Pending(
                flow, provider, verifier, System.currentTimeMillis()))
            val customTab = CustomTabsIntent.Builder()
                .setShowTitle(true)
                .setDefaultColorSchemeParams(
                    CustomTabColorSchemeParamsForVainah.params())
                .build()
            runCatching {
                customTab.launchUrl(this, Uri.parse(expected))
            }.onFailure {
                runCatching {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(expected)))
                }.onFailure {
                    message = "Не удалось открыть окно авторизации."
                }
            }
            render()
        }
    }

    private fun handleOAuthCallback(incoming: Intent): Boolean {
        val uri = incoming.data ?: return false
        if (uri.scheme != "vainahvpn" || uri.host != "oauth"
            || uri.path.orEmpty() !in setOf("", "/")
            || uri.fragment != null) return false
        val flow = uri.getQueryParameter("flow").orEmpty()
        val code = uri.getQueryParameter("code").orEmpty()
        // One-use code by itself is never a session. Only the app holds
        // the encrypted S256 verifier needed to exchange it over HTTPS.
        val pending = api.pendingOAuth()
        if (pending == null || !NativeOAuthFlow.validPending(pending) ||
            !NativeOAuthFlow.validFlow(flow) ||
            !NativeOAuthFlow.validCode(code) ||
            pending.flow != flow) {
            message = "Вход не подтверждён. Начни вход через приложение заново."
            render()
            return true
        }
        if (busy) {
            queuedOAuthCallback = incoming
            return true
        }
        perform({
            api.post("/api/mobile-auth/exchange", JSONObject()
                .put("flow", flow)
                .put("code", code)
                .put("verifier", pending.verifier))
        }) { result ->
            if (result.getOrNull()?.ok == true && api.hasSession()) {
                api.clearOAuthPending()
                otpRequested = false
                message = null
                refresh()
            } else {
                val status = result.getOrNull()?.status
                if (status == 400 || status == 401) api.clearOAuthPending()
                message = if (status == 400 || status == 401)
                    "Код входа уже использован или истёк. Повтори вход."
                else "Не удалось завершить вход. Проверь соединение и повтори."
                render()
            }
        }
        return true
    }

    private fun dp(x: Int) = VainahUi.dp(this, x)
    private fun col() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
    }
    private fun row() = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
    private fun add(parent: LinearLayout, child: View, margin: Int = 0) {
        parent.addView(child, LinearLayout.LayoutParams(-1, -2).apply {
            topMargin = dp(margin)
        })
    }
    private fun label(value: String, size: Float = 13f, color: Int = ink,
                      strong: Boolean = false): TextView = TextView(this).apply {
        text = value
        textSize = size
        setTextColor(color)
        if (strong) typeface = Typeface.create("sans-serif-medium", Typeface.BOLD)
        setLineSpacing(dp(2).toFloat(), 1f)
    }
    private fun card() = col().apply {
        setPadding(dp(17), dp(16), dp(17), dp(17))
        background = VainahUi.cardBackground(this@NativeCabinetActivity)
        elevation = dp(2).toFloat()
    }
    private fun action(value: String, primary: Boolean = false): Button =
        Button(this).apply {
            text = value
            textSize = 12f
            isAllCaps = false
            minHeight = dp(46)
            minimumHeight = dp(46)
            setPadding(dp(10), 0, dp(10), 0)
            setTextColor(if (primary) Color.WHITE else ink)
            background = VainahUi.buttonBackground(this@NativeCabinetActivity, primary)
        }
    private fun field(hint: String, code: Boolean = false): EditText =
        EditText(this).apply {
            setSingleLine(true)
            textSize = 14f
            setTextColor(ink)
            setHintTextColor(muted)
            setPadding(dp(13), dp(12), dp(13), dp(12))
            this.hint = hint
            inputType = if(code) InputType.TYPE_CLASS_NUMBER
                else InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS
            if (code) filters = arrayOf(android.text.InputFilter.LengthFilter(6))
            imeOptions = EditorInfo.IME_ACTION_DONE
            background = GradientDrawable().apply {
                setColor(Color.rgb(251, 249, 255))
                cornerRadius = dp(14).toFloat()
                setStroke(dp(1), VainahDesign.border)
            }
        }
    private fun miniLabel(value: String) = label(value, 10.5f, muted, true)

    private fun <T> perform(work: () -> T, after: (Result<T>) -> Unit) {
        if (busy) return
        busy = true
        render()
        executor.execute {
            val result = runCatching(work)
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                busy = false
                after(result)
                val queued = queuedOAuthCallback
                if (!busy && queued != null) {
                    queuedOAuthCallback = null
                    handleOAuthCallback(queued)
                }
            }
        }
    }

    private data class Loaded(
        val plans: NativeCabinetCatalog.Snapshot?,
        val payment: Boolean,
        val trial: JSONObject?,
        val email: String?,
        val telegram: String?,
        val dashboard: JSONObject?,
        val trialState: JSONObject?,
        val socialConfig: JSONObject?,
        val emailConfig: JSONObject?
    )

    private fun refresh() {
        perform({
            val plans = runCatching {
                api.get(NativeCabinetCatalog.CATALOG_ENDPOINT)
                    .takeIf { it.ok }?.json?.let {
                        NativeCabinetCatalog.parse(it.toString())
                    }
            }.getOrNull()
            val checkout = runCatching {
                api.get(NativeCabinetCatalog.CHECKOUT_STATUS_ENDPOINT)
                    .json?.optBoolean("checkout_ready", false) ?: false
            }.getOrDefault(false)
            val trial = runCatching {
                api.get(NativeCabinetCatalog.TRIAL_ENDPOINT).json
            }.getOrNull()
            val social = runCatching {
                api.get("/api/mobile-auth/config").takeIf { it.ok }?.json
            }.getOrNull()
            val emailConfig = runCatching {
                api.get("/api/email-auth/config").takeIf { it.ok }?.json
            }.getOrNull()
            val auth = runCatching {
                api.get("/api/email-auth/account").json
            }.getOrNull()
            val email = if (auth?.optBoolean("authenticated") == true)
                auth.optJSONObject("user")?.optString("email")?.take(254) else null
            val telegram = if (email == null &&
                api.authCookieName() == "__Host-vainah_session")
                runCatching {
                    api.get("/api/telegram/account").takeIf { it.ok }
                        ?.json?.takeIf { it.optBoolean("authenticated") }
                        ?.optJSONObject("user")
                        ?.let {
                            val username = it.optString("username").take(32)
                            if (username.isNotBlank()) "@$username" else
                                "Telegram ID " + it.optString("telegram_id").take(18)
                        }
                }.getOrNull()
            else null
            val overview = if (email != null || telegram != null) runCatching {
                api.get("/api/account/overview").takeIf { it.ok }?.json
            }.getOrNull() else null
            val trialStatus = if (email != null) runCatching {
                api.get("/api/trial/status").takeIf { it.ok }?.json
            }.getOrNull() else null
            Loaded(plans, checkout, trial, email, telegram, overview,
                trialStatus, social, emailConfig)
        }) { result ->
            result.onSuccess {
                catalog = it.plans
                checkoutReady = it.payment
                trialConfig = it.trial
                signedInEmail = it.email
                telegramIdentity = it.telegram
                account = it.dashboard
                trialStatus = it.trialState
                googleAvailable = it.socialConfig?.optBoolean("google") == true
                telegramAvailable = it.socialConfig?.optBoolean("telegram") == true
                emailConfigKnown = it.emailConfig != null
                emailConfigured = it.emailConfig?.optBoolean("available") == true
                if (it.plans == null) message = "Не удалось загрузить тарифы. Проверь интернет."
            }.onFailure {
                message = "Нет связи с личным кабинетом. Подключение VPN не затронуто."
            }
            render()
        }
    }

    private fun render() {
        val position = scroll?.scrollY ?: 0
        val root = col().apply {
            background = VainahUi.pageBackground()
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                setOnApplyWindowInsetsListener { v, insets ->
                    val bars = insets.getInsets(android.view.WindowInsets.Type.systemBars())
                    v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
                    insets
                }
            } else fitsSystemWindows = true
        }
        val top = row().apply {
            setPadding(dp(13), dp(10), dp(13), dp(8))
        }
        val back = action("‹").apply {
            textSize = 23f
            contentDescription = "Назад в VainahVPN"
        }
        top.addView(back, LinearLayout.LayoutParams(dp(48), dp(44)))
        back.setOnClickListener { finish() }
        top.addView(VainahShieldView(this), LinearLayout.LayoutParams(
            dp(31), dp(31)).apply { marginStart = dp(9) })
        top.addView(label("VainahVPN", 19f, ink, true),
            LinearLayout.LayoutParams(0, -2, 1f).apply { marginStart = dp(9) })
        val refresh = action("↻")
        top.addView(refresh, LinearLayout.LayoutParams(dp(48), dp(44)))
        refresh.isEnabled = !busy
        refresh.contentDescription = "Обновить данные личного кабинета"
        refresh.setOnClickListener { message = null; refresh() }
        add(root, top)

        val selection = row().apply { setPadding(dp(16), 0, dp(16), dp(9)) }
        for ((id, title) in listOf("cabinet" to "Кабинет", "plans" to "Тарифы")) {
            val button = action(title, id == page)
            button.isEnabled = !busy
            selection.addView(button, LinearLayout.LayoutParams(0, dp(44), 1f).apply {
                if(id == "plans") marginStart = dp(9)
            })
            button.setOnClickListener {
                page = id
                shown = 12
                scroll?.scrollTo(0,0)
                render()
            }
        }
        add(root, selection)
        val sc = ScrollView(this).apply {
            isFillViewport = false
            clipToPadding = false
        }
        val body = col().apply {
            setPadding(dp(15), dp(2), dp(15), dp(26))
        }
        sc.addView(body)
        root.addView(sc, LinearLayout.LayoutParams(-1, 0, 1f))
        scroll = sc

        if (busy) add(body, VainahUi.infoStrip(this,
            "Загружаем данные с сервера VainahVPN…"), 7)
        message?.let { add(body, VainahUi.infoStrip(this, it), 7) }
        // The free trial is ALWAYS the first meaningful card in both tabs.
        renderTrial(body)
        if (page == "cabinet") {
            renderAccount(body)
            renderFeatured(body)
        } else {
            renderCatalog(body)
        }
        setContentView(root)
        if(position > 0) sc.post { sc.scrollTo(0, position) }
    }

    private fun renderTrial(body: LinearLayout) {
        val box = card()
        add(body, box, 8)
        add(box, VainahUi.statusPill(this, "ПРОБНЫЙ ПЕРИОД",
            VainahUi.Tone.PURPLE))
        add(box, label("Попробуй VainahVPN", 21f, ink, true), 11)
        val config = trialConfig
        val available = config?.optBoolean("available", false) == true
        val trial = catalog?.trial
        val terms = if (config != null)
            "${config.optInt("days", 1)} день · ${config.optInt("devices", 2)} устройства · " +
                "${config.optInt("traffic_gb", 10)} ГБ"
        else if (trial != null)
            "${trial.durationLabel} · ${trial.devices} устройства"
        else "Условия уточняются на сервере"
        add(box, label(terms, 13f, muted), 9)
        add(box, label("0 ₽ · один раз для нового аккаунта", 17f,
            VainahDesign.green, true), 8)
        val state = trialStatus?.optString("status")
        val statusText = when(state) {
            "delivered" -> "Пробный доступ уже выдан"
            "claimed" -> "Запрос уже зарегистрирован"
            "manual_review" -> "Требуется проверка оператором"
            "eligible" -> if(available) "Можно активировать после входа"
                else "Выдача временно недоступна"
            else -> if(signedInEmail == null)
                "Для активации войди по email" else "Статус уточняется"
        }
        add(box, label(statusText, 11.5f, muted), 6)
        val trialButton = action(
            when {
                signedInEmail == null -> "Войти и попробовать"
                state == "delivered" -> "Настроить пробный VPN"
                else -> "Получить пробный доступ"
            }, true)
        trialButton.isEnabled = !busy &&
            (signedInEmail == null || state == "delivered" ||
                (available && state == "eligible" &&
                    trialStatus?.optBoolean("can_claim") == true))
        add(box, trialButton, 13)
        trialButton.setOnClickListener {
            when {
                signedInEmail == null -> { page = "cabinet"; render() }
                state == "delivered" -> importTrialFromStatus()
                else -> confirmClaim()
            }
        }
        if(config == null) add(box, label(
            "Если сервер недоступен, пробный доступ не активируется автоматически.",
            11f, muted), 8)
    }

    private fun emailFailure(reply: NativeCabinetApi.Reply?): String {
        val detail = reply?.json?.optString("detail").orEmpty()
        return when {
            reply == null -> "Нет связи с сервером. Проверь интернет и адрес сайта."
            detail == "EMAIL_LOGIN_COOLDOWN" ->
                "Код уже запрашивали. Подожди 90 секунд перед повтором."
            detail == "EMAIL_LOGIN_LIMIT" || reply.status == 429 ->
                "Слишком много запросов. Повтори позже."
            detail == "EMAIL_LOGIN_NOT_CONFIGURED" ||
                detail == "EMAIL_DELIVERY_NOT_CONFIGURED" ->
                "Email-вход пока не настроен на сервере. Проверь Resend и домен отправителя."
            detail == "EMAIL_DELIVERY_UNAVAILABLE" ->
                "Почтовый сервис не принял письмо. Проверь API-ключ и " +
                    "подтверждение адреса отправителя в Resend."
            detail == "EMAIL_LOGIN_DATABASE_UNAVAILABLE" ->
                "Почтовая авторизация недоступна: сервер не отвечает базе данных."
            detail == "INVALID_ORIGIN" || reply.status == 403 ->
                "Сайт и API не совпадают: проверь PUBLIC_SITE_ORIGIN в Render."
            reply.status == 422 -> "Адрес email не прошёл проверку."
            else -> "Код не отправлен. Ошибка сервера: HTTP ${reply.status}."
        }
    }

    private fun renderAccount(body: LinearLayout) {
        val box = card()
        add(body, box, 13)
        add(box, miniLabel("МОЙ АККАУНТ"))
        add(box, label(if(signedInEmail != null || telegramIdentity != null)
            "Добро пожаловать" else "Вход в VainahVPN", 19f, ink, true), 6)
        if (signedInEmail == null && telegramIdentity == null) {
            val providers = row()
            val google = action("Войти с Google", googleAvailable)
            google.isEnabled = !busy && googleAvailable
            google.contentDescription = "Войти в VainahVPN с Google"
            providers.addView(google,
                LinearLayout.LayoutParams(0, dp(48), 1f))
            google.setOnClickListener { beginSocialLogin("google") }
            val telegram = action("Войти с Telegram", telegramAvailable)
            telegram.isEnabled = !busy && telegramAvailable
            telegram.contentDescription = "Войти в VainahVPN с Telegram"
            providers.addView(telegram,
                LinearLayout.LayoutParams(0, dp(48), 1f).apply {
                    marginStart = dp(8)
                })
            telegram.setOnClickListener { beginSocialLogin("telegram") }
            add(box, providers, 12)
            if (!googleAvailable || !telegramAvailable) {
                add(box, label("Недоступные кнопки требуют настройки " +
                    "Google или Telegram OIDC на сервере.", 11f, muted), 7)
            }
            add(box, label("Или получи код по email. Используй ту же почту, " +
                "что на сайте, чтобы увидеть свои заказы.", 12f, muted), 13)
            if (emailConfigKnown && !emailConfigured) {
                add(box, VainahUi.infoStrip(this,
                    "Отправка писем не настроена. Проверь RESEND_API_KEY, " +
                        "VAINAH_EMAIL_FROM и подтверждение домена в Resend."), 9)
            }
            val email = field("Электронная почта")
            email.setText(pendingEmail)
            add(box, email, 12)
            if (!otpRequested) {
                val request = action("Получить код", true)
                request.isEnabled = !busy && (!emailConfigKnown || emailConfigured)
                add(box, request, 10)
                request.setOnClickListener {
                    pendingEmail = email.text.toString().trim()
                    if (!pendingEmail.contains('@') || pendingEmail.length !in 5..254) {
                        message = "Укажи корректный email."
                        render()
                    } else perform({
                        api.post("/api/email-auth/request",
                            JSONObject().put("email", pendingEmail))
                    }) { result ->
                        val reply = result.getOrNull()
                        otpRequested = reply?.ok == true
                        message = if (otpRequested)
                            "Запрос принят. Проверь «Входящие» и «Спам». " +
                                "Код действует 10 минут; доставку письма проверяет Resend."
                        else emailFailure(reply)
                        render()
                    }
                }
            } else {
                val code = field("Шестизначный код", code = true)
                add(box, code, 9)
                val confirm = action("Войти", true)
                confirm.isEnabled = !busy
                add(box, confirm, 9)
                confirm.setOnClickListener {
                    val value = code.text.toString()
                    if (!value.matches(Regex("[0-9]{6}"))) {
                        message = "Введи шестизначный код."
                        render()
                    } else perform({
                        api.post("/api/email-auth/verify",
                            JSONObject().put("email", pendingEmail).put("code", value))
                    }) { result ->
                        if (result.getOrNull()?.ok == true && api.hasSession()) {
                            otpRequested = false
                            message = null
                            refresh()
                        } else {
                            message = if (result.getOrNull()?.status == 403)
                                "Ошибка адреса сайта: проверь PUBLIC_SITE_ORIGIN."
                            else "Код неверный или истёк. Запроси новый."
                            render()
                        }
                    }
                }
                val another = action("Запросить другой код")
                add(box, another, 8)
                another.setOnClickListener {
                    otpRequested = false
                    message = "Новый код можно запросить после 90 секунд. " +
                        "Проверь также папку «Спам»."
                    render()
                }
            }
            return
        }

        if (signedInEmail != null) {
            add(box, VainahUi.detailRow(this, "Подтверждённая почта",
                signedInEmail!!.take(42), VainahUi.Tone.SUCCESS), 12)
        } else {
            add(box, VainahUi.detailRow(this, "Telegram",
                telegramIdentity.orEmpty().take(42), VainahUi.Tone.SUCCESS), 12)
            add(box, VainahUi.infoStrip(this,
                "Telegram не подтверждает email. Для пробного периода и " +
                    "оплаты нужен подтверждённый email-аккаунт."), 9)
            val emailLogin = action("Войти по email для покупок")
            add(box, emailLogin, 10)
            emailLogin.setOnClickListener {
                AlertDialog.Builder(this)
                    .setTitle("Войти по email?")
                    .setMessage("Вход по email заменит текущую сессию Telegram " +
                        "в приложении. Существующая подписка VPN не изменится.")
                    .setNegativeButton("Отмена", null)
                    .setPositiveButton("Продолжить") { _, _ ->
                        api.forgetSession()
                        telegramIdentity = null
                        signedInEmail = null
                        otpRequested = false
                        render()
                    }.show()
            }
        }
        val subscribed = account?.optJSONObject("subscription")
        add(box, VainahUi.detailRow(this, "Подписка",
            subscribed?.optString("plan_title")?.takeIf { it.isNotBlank() }
                ?: "Не подтверждена"), 8)
        if (subscribed != null) {
            add(box, VainahUi.detailRow(this, "Устройств в тарифе",
                subscribed.optInt("device_limit", 0).let {
                    if(it > 0) it.toString() else "Неизвестно"
                }), 7)
            val expires = subscribed.optString("expires_at")
            if (expires.isNotBlank() && expires != "null") {
                add(box, label("Действует до: " +
                    expires.take(10), 12f, muted), 8)
            }
        }
        val orderCount = account?.optJSONArray("orders")?.length()
        add(box, VainahUi.detailRow(this, "Заказов",
            orderCount?.toString() ?: "Нет данных"), 8)
        val logout = action("Выйти из кабинета")
        add(box, logout, 12)
        logout.setOnClickListener {
            perform({
                runCatching { api.post("/api/email-auth/logout") }
                api.forgetSession()
                true
            }) {
                signedInEmail = null
                telegramIdentity = null
                account = null
                trialStatus = null
                message = "Вход завершён."
                render()
            }
        }
        renderOrders(body)
    }

    private fun renderOrders(body: LinearLayout) {
        val items = account?.optJSONArray("orders") ?: return
        if (items.length() == 0) return
        val box = card()
        add(body, box, 12)
        add(box, miniLabel("МОИ ЗАКАЗЫ"))
        for (i in 0 until minOf(5, items.length())) {
            val order = items.optJSONObject(i) ?: continue
            val title = order.optString("plan_title").takeIf { it.isNotBlank() }
                ?: order.optString("plan_id", "Тариф").take(30)
            val paid = order.optBoolean("paid", false)
            val delivered = order.optBoolean("delivered", false)
            add(box, VainahUi.detailRow(this, title,
                when {
                    paid && delivered -> "Выдан"
                    paid -> "Ожидает выдачи"
                    else -> "Без оплаты"
                }, if(paid && delivered) VainahUi.Tone.SUCCESS
                else VainahUi.Tone.NEUTRAL), 7)
        }
        if(items.length() > 5) add(box, label(
            "Показаны последние 5 из ${items.length()} заказов",
            11f, muted), 8)
    }

    private fun renderFeatured(body: LinearLayout) {
        val items = catalog?.paid.orEmpty()
        val favorites = listOf("30", "90", "365").mapNotNull { id ->
            items.firstOrNull { it.id == id }
        }.ifEmpty { items.take(3) }
        val box = card()
        add(body, box, 13)
        add(box, miniLabel("ПОПУЛЯРНЫЕ ТАРИФЫ"))
        add(box, label("Выбери подписку", 18f, ink, true), 7)
        if(favorites.isEmpty()) add(box, label("Тарифы пока не загружены.",
            12f, muted), 9)
        for(plan in favorites) renderPlan(box, plan, compact = true)
        val all = action("Посмотреть все тарифы", true)
        add(box, all, 12)
        all.setOnClickListener {
            page = "plans"
            scroll?.scrollTo(0, 0)
            render()
        }
    }

    private fun renderCatalog(body: LinearLayout) {
        val box = card()
        add(body, box, 13)
        val items = catalog?.paid.orEmpty()
        add(box, miniLabel("КАТАЛОГ VAINAHVPN"))
        add(box, label("${items.size} платных тарифов", 19f, ink, true), 7)
        add(box, label(if(checkoutReady)
            "После выбора откроется защищённое оформление на сайте."
        else "Приём платежей временно недоступен. Цены загружены с сервера.",
            12f, muted), 7)

        val filters = listOf(
            "all" to "Все", "personal" to "Для себя",
            "family" to "Семья", "short" to "До 21 дня", "long" to "Долгие"
        )
        val filtersWrap = android.widget.HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
        }
        val filterRow = row()
        for ((id, label) in filters) {
            val chip = VainahUi.chip(this, label, category == id)
            chip.isClickable = true
            chip.isFocusable = true
            chip.setOnClickListener {
                category = id
                shown = 12
                render()
            }
            filterRow.addView(chip, LinearLayout.LayoutParams(-2, dp(38)).apply {
                marginEnd = dp(7)
            })
        }
        filtersWrap.addView(filterRow)
        add(box, filtersWrap, 14)
        val filtered = items.filter {
            when(category) {
                "personal" -> it.category == "personal"
                "family" -> it.category == "family"
                "short" -> it.days <= 21
                "long" -> it.days >= 120
                else -> true
            }
        }
        if(filtered.isEmpty()) {
            add(box, label("Нет тарифов по этому фильтру.", 12f, muted), 14)
        }
        for (plan in filtered.take(shown)) renderPlan(box, plan, compact = false)
        if (filtered.size > shown) {
            val more = action("Показать ещё ${minOf(12, filtered.size - shown)}")
            add(box, more, 12)
            more.setOnClickListener {
                shown += 12
                render()
            }
        }
        if(items.isEmpty()) {
            val refresh = action("Обновить каталог")
            add(box, refresh, 13)
            refresh.setOnClickListener { refresh() }
        }
    }

    private fun renderPlan(box: LinearLayout, plan: NativeCabinetCatalog.Plan,
                           compact: Boolean) {
        val item = col().apply {
            setPadding(dp(13), dp(12), dp(13), dp(12))
            background = GradientDrawable().apply {
                setColor(Color.rgb(250, 247, 255))
                cornerRadius = dp(17).toFloat()
                setStroke(dp(1), VainahDesign.border)
            }
        }
        add(box, item, 9)
        val header = row()
        header.addView(label(plan.title, 14.5f, ink, true),
            LinearLayout.LayoutParams(0, -2, 1f))
        header.addView(label(plan.priceLabel, 15f, violet, true))
        add(item, header)
        add(item, label("${plan.durationLabel} · ${plan.devices} устройства" +
            if (plan.tag.isNotBlank() && !compact) " · ${plan.tag}" else "",
            11.5f, muted), 5)
        val choose = action(if (checkoutReady) "Выбрать тариф" else
            "Оплата пока недоступна", checkoutReady)
        choose.isEnabled = !busy && checkoutReady
        add(item, choose, 9)
        choose.setOnClickListener { openCheckout(plan) }
    }

    private fun openCheckout(plan: NativeCabinetCatalog.Plan) {
        val url = NativeCabinetCatalog.checkoutUrl(plan, checkoutReady) ?: return
        // Recheck server readiness immediately BEFORE leaving native UI.
        perform({
            api.get(NativeCabinetCatalog.CHECKOUT_STATUS_ENDPOINT)
                .takeIf { it.ok }?.json?.optBoolean("checkout_ready") == true
        }) { result ->
            checkoutReady = result.getOrNull() == true
            if (checkoutReady) {
                val intent = CustomTabsIntent.Builder()
                    .setShowTitle(true)
                    .setDefaultColorSchemeParams(
                        CustomTabColorSchemeParamsForVainah.params()
                    ).build()
                runCatching { intent.launchUrl(this, Uri.parse(url)) }
                    .onFailure {
                        runCatching { startActivity(Intent(Intent.ACTION_VIEW,
                            Uri.parse(url))) }
                            .onFailure {
                                message = "Не удалось открыть защищённое оформление."
                            }
                    }
            } else {
                message = "Касса пока не подтверждена сервером. Счёт не создавался."
            }
            render()
        }
    }

    private fun confirmClaim() {
        AlertDialog.Builder(this)
            .setTitle("Активировать пробный период?")
            .setMessage("Бесплатно один раз на аккаунт: 1 день, 2 устройства, " +
                "10 ГБ. После выдачи сервером повторная активация не предусмотрена.")
            .setNegativeButton("Отмена", null)
            .setPositiveButton("Активировать") { _, _ ->
                perform({
                    api.post("/api/trial/claim")
                }) { result ->
                    val reply = result.getOrNull()
                    if (reply?.ok == true && reply.json?.optString("status") == "delivered") {
                        message = "Пробный период выдан сервером. Выбери «Настроить пробный VPN»."
                        refresh()
                    } else {
                        message = if (reply?.status == 409)
                            "Пробный период уже использован или недоступен аккаунту."
                        else "Выдача сейчас не подтверждена. Проверь статус перед повтором."
                        render()
                    }
                }
            }.show()
    }

    private fun importTrialFromStatus() {
        perform({
            api.get("/api/trial/status")
        }) { result ->
            val json = result.getOrNull()?.takeIf { it.ok }?.json
            val link = if (json?.optString("status") == "delivered")
                json.optString("subscription_url") else ""
            if (!link.startsWith("https://") || link.length > 4096) {
                message = "Пробный ключ пока не доступен. Обнови статус."
                render()
                return@perform
            }
            val store = SubscriptionController(this)
            val oldExists = store.savedLink() != null
            AlertDialog.Builder(this)
                .setTitle("Подключить пробную подписку?")
                .setMessage(if(oldExists)
                    "Это заменит сохранённый VPN-профиль. Перед заменой сохрани " +
                        "ссылку текущей подписки в надёжном месте."
                else "Добавить выданную пробную подписку в VainahVPN?")
                .setNegativeButton("Отмена", null)
                .setPositiveButton("Сохранить профиль") { _, _ ->
                    if (store.saveLink(link)) {
                        message = "Пробный профиль сохранён. Обнови серверы на главной."
                    } else {
                        message = "Не удалось сохранить пробный профиль."
                    }
                    render()
                }.show()
        }
    }
}

/** Single shared color configuration for the browser-hosted checkout only. */
internal object CustomTabColorSchemeParamsForVainah {
    fun params(): androidx.browser.customtabs.CustomTabColorSchemeParams =
        androidx.browser.customtabs.CustomTabColorSchemeParams.Builder()
            .setToolbarColor(VainahDesign.purple)
            .build()
}
