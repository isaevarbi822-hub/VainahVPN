package app.vainah.vpn

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.VpnService
import android.provider.Settings
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/**
 * Vainah VPN Next. No fake VPN status, embedded billing, WebView or hard-coded
 * deprecated hosting dependency. Subscription fetching lives in SubscriptionController;
 * VainahVpnService exclusively owns the real libbox VPN session.
 */
class MainActivity : Activity() {
    private enum class Page { HOME, LOCATIONS, ACCOUNT, DEVICES, DIAGNOSTICS, SECURITY, SETTINGS, MORE }
    private var page = Page.HOME
    private lateinit var source: SubscriptionController
    private var nodes: List<VainahNode> = emptyList()
    private var selected: VainahNode? = null
    private var pendingNode: VainahNode? = null
    private var lastError: String? = null
    private var cacheMessage = "Серверы ещё не обновлены"
    private var nextAutoRefresh = 0L
    private var serverProbeRunning = false
    private var serverProbeGeneration = 0
    private var serverProbeMessage = "TCP-задержка входных узлов ещё не измерялась."
    private var serverProbes: List<ServerTcpObservation> = emptyList()
    private var serverListExpanded = false
    private var routeScanVersion = 0
    private var routeScanRunning = false
    private var routeSnapshot: VpnNetworkFacts? = null
    private var routeNetworkSnapshot: VpnUnderlayStatus.Snapshot? = null
    private var routeConnectionSnapshot: VpnConnectionState.Snapshot? = null
    private var stateView: TextView? = null
    private var detailView: TextView? = null
    private var trafficView: TextView? = null
    private var connectView: Button? = null
    private val main = Handler(Looper.getMainLooper())
    private val vpnConsentCode = 7041

    private val bg = Color.rgb(10, 14, 27)
    private val card = Color.rgb(23, 29, 48)
    private val border = Color.rgb(59, 66, 90)
    private val violet = Color.rgb(165, 138, 249)
    private val white = Color.rgb(244, 244, 255)
    private val grey = Color.rgb(169, 178, 202)
    private val teal = Color.rgb(107, 219, 230)
    private val green = Color.rgb(111, 221, 176)
    private val errorColor = Color.rgb(249, 173, 164)

    private val ticker = object : Runnable {
        override fun run() {
            updateConnection()
            maybeRefresh()
            main.postDelayed(this, 2300)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = bg
        window.navigationBarColor = bg
        source = SubscriptionController(this)
        page = savedInstanceState?.getString("page")?.let {
            runCatching { Page.valueOf(it) }.getOrNull()
        } ?: Page.HOME
        nodes = source.cachedNodes()
        selected = nodes.firstOrNull()
        if (nodes.isNotEmpty()) cacheMessage =
            "Последний сохранённый список. Актуальность не подтверждена."
        render()
    }
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString("page", page.name)
        super.onSaveInstanceState(outState)
    }
    override fun onResume() {
        super.onResume()
        // A service may have disconnected/reconnected while the activity
        // was paused. Never present old routes as a fresh VPN observation.
        routeScanVersion++
        routeScanRunning = false
        routeSnapshot = null
        routeNetworkSnapshot = null
        routeConnectionSnapshot = null
        main.removeCallbacks(ticker)
        main.post(ticker)
    }
    override fun onPause() {
        main.removeCallbacks(ticker)
        super.onPause()
    }
    override fun onDestroy() {
        routeScanVersion++
        serverProbeGeneration++
        source.invalidate()
        main.removeCallbacks(ticker)
        super.onDestroy()
    }

    private fun dp(n: Int) = (resources.displayMetrics.density * n).toInt()
    private fun column() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    private fun horizontal() = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
    }
    private fun shape(color: Int, edge: Int = border, radius: Int = 18) =
        GradientDrawable().apply {
            setColor(color)
            cornerRadius = dp(radius).toFloat()
            setStroke(dp(1), edge)
        }
    private fun add(parent: LinearLayout, view: View, top: Int = 0) {
        parent.addView(view, LinearLayout.LayoutParams(-1, -2).apply {
            topMargin = dp(top)
        })
    }
    private fun t(
        content: String, size: Float = 14f, color: Int = white,
        heavy: Boolean = false
    ) = TextView(this).apply {
        text = content
        textSize = size
        setTextColor(color)
        if (heavy) typeface = Typeface.create("sans-serif", Typeface.BOLD)
        setLineSpacing(dp(2).toFloat(), 1.05f)
    }
    private fun card() = column().apply {
        background = shape(card)
        setPadding(dp(19), dp(20), dp(19), dp(22))
    }
    private fun tag(value: String) = t(value.uppercase(), 11f, violet, true).apply {
        letterSpacing = 0.1f
    }
    private fun action(value: String, mainButton: Boolean = false) = Button(this).apply {
        text = value
        isAllCaps = false
        textSize = 14f
        minHeight = dp(52)
        typeface = Typeface.create("sans-serif-medium", Typeface.BOLD)
        setTextColor(if (mainButton) bg else white)
        background = shape(if (mainButton) violet else card,
            if (mainButton) violet else border, 14)
    }
    private fun input(hintValue: String) = EditText(this).apply {
        hint = hintValue
        setSingleLine(true)
        textSize = 13f
        setTextColor(white)
        setHintTextColor(grey)
        setPadding(dp(13), dp(14), dp(13), dp(14))
        background = shape(bg, border, 12)
        importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO
    }
    private fun popup(message: String) {
        AlertDialog.Builder(this).setTitle("Vainah VPN").setMessage(message)
            .setPositiveButton("Понятно", null).show()
    }

    private fun render() {
        stateView = null
        detailView = null
        trafficView = null
        connectView = null
        val light = page == Page.HOME || page == Page.LOCATIONS
        val frame = column().apply {
            setBackgroundColor(if (light) ServerListVisual.backgroundColor() else bg)
        }
        val scroll = ScrollView(this).apply { isFillViewport = true }
        val body = column().apply {
            setPadding(dp(if (light) 14 else 20), dp(if (light) 18 else 28),
                dp(if (light) 14 else 20), dp(28))
        }
        scroll.addView(body)
        frame.addView(scroll, LinearLayout.LayoutParams(-1, 0, 1f))
        add(body, tag("VAINAH VPN / NEXT"))
        add(body, t(when (page) {
            Page.HOME -> "Твоё соединение. Твои правила."
            Page.LOCATIONS -> "Серверы и локации"
            Page.ACCOUNT -> "Мой VPN"
            Page.DEVICES -> "Мои устройства"
            Page.DIAGNOSTICS -> "Диагностика"
            Page.SECURITY -> "Безопасность"
            Page.SETTINGS -> "Настройки"
            Page.MORE -> "Больше возможностей"
        }, if (light) 22f else 25f,
            if (light) ServerListVisual.textColor() else white, true), 8)
        add(body, t("Android · " + BuildConfig.VERSION_NAME, 12f,
            if (light) ServerListVisual.mutedColor() else grey), 7)
        when (page) {
            Page.HOME -> home(body)
            Page.LOCATIONS -> locations(body)
            Page.ACCOUNT -> account(body)
            Page.DEVICES -> devices(body)
            Page.DIAGNOSTICS -> help(body)
            Page.SECURITY -> security(body)
            Page.SETTINGS -> settings(body)
            Page.MORE -> more(body)
        }
        val nav = horizontal().apply {
            setBackgroundColor(if (light) ServerListVisual.cardColor() else card)
            setPadding(dp(12), dp(9), dp(12), dp(9))
        }
        val selectedTab = if (page in listOf(Page.DEVICES, Page.DIAGNOSTICS,
                Page.SECURITY, Page.SETTINGS)) Page.MORE else page
        for ((target, label) in listOf(
            Page.HOME to "Главная", Page.LOCATIONS to "Серверы",
            Page.ACCOUNT to "Мой VPN", Page.MORE to "Ещё"
        )) {
            val button = action(label, target == selectedTab).apply {
                minHeight = dp(44)
                textSize = 12f
                if (light && target != selectedTab) {
                    setTextColor(ServerListVisual.textColor())
                    background = shape(
                        ServerListVisual.cardColor(),
                        ServerListVisual.backgroundColor(), 13
                    )
                }
                setOnClickListener {
                    if (target != page) {
                        page = target
                        render()
                    }
                }
            }
            nav.addView(button, LinearLayout.LayoutParams(0, dp(48), 1f).apply {
                marginStart = dp(3)
                marginEnd = dp(3)
            })
        }
        frame.addView(nav)
        setContentView(frame)
        updateConnection()
    }

    private fun home(body: LinearLayout) {
        val connection = card()
        add(body, connection, 21)
        add(connection, tag("Соединение"))
        val status = t("Не подключено", 23f, white, true)
        stateView = status
        add(connection, status, 10)
        val detail = t("Выбери сервер и проверь свой IP в браузере.", 13f, grey)
        detailView = detail
        add(connection, detail, 9)
        add(connection, t(
            selected?.label ?: "Сервер не выбран",
            14f, if (selected == null) grey else teal, true
        ), 13)
        val connect = action("Подключиться", true)
        connectView = connect
        add(connection, connect, 17)
        connect.setOnClickListener {
            if (VpnConnectionState.read(this).canDisconnect) disconnect()
            else connect()
        }

        val metrics = card()
        add(body, metrics, 16)
        add(metrics, tag("Скорость и трафик"))
        val traffic = t("Статистика появится после подключения.", 13f, grey)
        trafficView = traffic
        add(metrics, traffic, 11)

        val list = card()
        add(body, list, 16)
        add(list, tag("Серверы и конфигурации"))
        add(list, t("Твои локации", 21f, white, true), 8)
        add(list, t(source.sourceLabel(), 12f, grey), 9)
        add(list, t(if (source.busy) "Обновляем серверы…" else cacheMessage, 12f, grey), 7)
        lastError?.let { add(list, t(it, 12f, errorColor), 10) }
        if (nodes.isEmpty()) {
            add(list, t("Список пока пуст. Добавь подписку или обнови серверы.",
                13f, grey), 12)
        } else {
            nodes.forEach { node ->
                val prefix = if (node.uri == selected?.uri) "✓  " else ""
                val select = action(prefix + node.label)
                add(list, select, 8)
                select.setOnClickListener { selected = node; render() }
            }
        }
        val refresh = action(if (source.busy) "Обновление…" else "Обновить серверы")
        refresh.isEnabled = !source.busy
        add(list, refresh, 17)
        refresh.setOnClickListener { refreshServers(true) }
        val manage = action("Добавить или изменить подписку")
        add(list, manage, 8)
        manage.setOnClickListener { page = Page.ACCOUNT; render() }
    }

    private fun account(body: LinearLayout) {
        val profile = card()
        add(body, profile, 21)
        add(profile, tag("VPN-профиль"))
        add(profile, t(if (source.savedLink() == null)
            "Подписка не добавлена" else "Профиль сохранён", 19f, white, true), 9)
        add(profile, t(source.sourceLabel(), 12f, grey), 8)
        add(profile, t(
            "HTTPS-подписки и собственные VLESS REALITY-ключи хранятся " +
                "в Android Keystore. Данные не попадают в отчёты.",
            12f, grey), 9)
        val entry = input("https://… или vless://…")
        add(profile, entry, 12)
        val save = action("Сохранить профиль", true)
        add(profile, save, 9)
        save.setOnClickListener {
            if (!source.saveLink(entry.text.toString())) {
                popup("Вставь полную HTTPS-подписку или корректный VLESS REALITY-ключ.")
                return@setOnClickListener
            }
            entry.text.clear()
            invalidateServerProbes()
            nodes = source.cachedNodes()
            selected = nodes.firstOrNull()
            lastError = null
            nextAutoRefresh = 0L
            cacheMessage = "Профиль сохранён. Обновляем список."
            page = Page.HOME
            render()
            refreshServers(true)
        }

        val options = card()
        add(body, options, 15)
        add(options, tag("Совместимость"))
        add(options, t(
            "Дополнительные заголовки отправляются только с твоего разрешения " +
                "и не гарантируют снятия HTTP 403.", 12f, grey), 8)
        val hwid = action(if (source.hwidEnabled())
            "HWID включён · выключить" else "HWID выключен · включить")
        add(options, hwid, 11)
        hwid.setOnClickListener {
            AlertDialog.Builder(this).setTitle("Передача HWID")
                .setMessage("Сервер получит отдельный ID Vainah VPN, модель " +
                    "и версию Android. Может использоваться дополнительный слот устройства.")
                .setNegativeButton("Отмена", null)
                .setPositiveButton("Изменить") { _, _ ->
                    source.setHwidEnabled(!source.hwidEnabled())
                    render()
                }.show()
        }
        val agent = input("User-Agent, разрешённый провайдером")
        add(options, agent, 11)
        val setAgent = action("Применить User-Agent")
        add(options, setAgent, 8)
        setAgent.setOnClickListener {
            if (source.saveUserAgent(agent.text.toString())) {
                agent.text.clear()
                popup("User-Agent сохранён в защищённом хранилище.")
                render()
            } else popup("Не удалось сохранить User-Agent (длина 5–180 символов).")
        }
        val reset = action("Вернуть стандартный User-Agent")
        add(options, reset, 8)
        reset.setOnClickListener { source.resetUserAgent(); render() }

        val identity = card()
        add(body, identity, 15)
        add(identity, tag("Учётная запись"))
        add(identity, t(
            "Clerk используется только для входа. Покупки в новой версии " +
                "пока выключены до полноценного переноса Python API.",
            12f, grey), 8)
        val login = action("Войти через Clerk")
        add(identity, login, 10)
        login.setOnClickListener {
            if (!BuildConfig.VAINAH_CLERK_ENABLED)
                popup("Clerk не включён в этой тестовой сборке.")
            else runCatching {
                startActivity(Intent().setClassName(this,
                    "app.vainah.vpn.ClerkLoginActivity"))
            }.onFailure { popup("Не удалось открыть окно Clerk.") }
        }
    }

    private fun help(body: LinearLayout) {
        val info = card()
        add(body, info, 21)
        add(info, tag("Диагностика"))
        add(info, t(
            "HTTP 403 означает, что сервер подписки отказал конкретному " +
                "приложению. Это не подтверждает окончание подписки.",
            13f, grey), 10)
        add(info, t(source.sourceLabel(), 12f, teal), 11)
        add(info, t("libbox: " + if (EngineRegistry.active.ready)
            "установлен" else "не установлен", 13f, grey), 10)
        lastError?.let { add(info, t("Ошибка: " + it, 13f, errorColor), 10) }
        add(info, t(
            "Состояние VPN берётся из Android-службы. Наличие TUN не подтверждает " +
                "внешний IP и отсутствие DNS-утечек.",
            12f, grey), 10)
        val network = VpnUnderlayStatus.read(this)
        val kind = when (network.transport) {
            "wifi" -> "Wi-Fi"
            "cellular" -> "4G / 5G"
            "ethernet" -> "Ethernet"
            "other" -> "другое подключение"
            else -> "нет подтверждённого интерфейса"
        }
        val connectionActive = VpnConnectionState.read(this).canDisconnect
        add(info, t(
            "Физическая сеть в VPN-сеансе: " + kind +
                (if (connectionActive) "" else " · последнее наблюдение"),
            13f, white, true
        ), 12)
        add(info, t(
            "Проверка сети Android: " +
                (if (network.validated) "подтверждена системой" else "не подтверждена") +
                " · переходов между интерфейсами: " + network.transitions,
            12f, grey), 6)
        add(info, t(
            "Это только состояние физической сети Android, не доказательство " +
                "работы VPN, доступа к сайтам или отсутствия DNS-утечек. " +
                "При смене Wi-Fi/4G libbox получает обновление интерфейса.",
            12f, grey), 8)

        val recovery = VpnUnderlayStatus.recovery(
            this, connectionActive && VainahVpnService.runningInProcess
        )
        val recoveryCard = card()
        add(body, recoveryCard, 16)
        add(recoveryCard, tag("ВОССТАНОВЛЕНИЕ СЕТИ"))
        add(recoveryCard, t(recovery.title, 17f, white, true), 8)
        add(recoveryCard, t(
            recovery.message, 12f, if (recovery.attention) errorColor else grey
        ), 8)
        add(recoveryCard, t(
            "VPN никогда не перезапускается автоматически при изменении сети. " +
                "Решение о ручном переподключении остаётся за тобой.",
            12f, grey
        ), 8)
        val reopen = action("Открыть управление подключением")
        add(recoveryCard, reopen, 10)
        reopen.setOnClickListener { page = Page.HOME; render() }
        val refreshRecovery = action("Обновить состояние сети")
        add(recoveryCard, refreshRecovery, 9)
        refreshRecovery.setOnClickListener { render() }

        val failedCode = getSharedPreferences("vpn_diagnostics", MODE_PRIVATE)
            .getString("last_failure_code", null)
        if (VpnConnectionState.read(this).phase == VpnConnectionState.FAILED &&
            failedCode != null
        ) {
            val engineAdvice = VpnFailureAdvisor.fromCode(failedCode)
            val recognized = VpnFailureAdvisor.sanitizedCode(failedCode)
            val failureCard = card()
            add(body, failureCard, 16)
            add(failureCard, tag("ДИАГНОСТИКА LIBBOX"))
            add(failureCard, t(
                engineAdvice.title, 16f, white, true
            ), 8)
            add(failureCard, t(
                engineAdvice.action, 12f, grey
            ), 8)
            add(failureCard, t("Код ошибки: " + recognized, 12f, teal), 8)
        }

        val routes = card()
        add(body, routes, 16)
        add(routes, tag("DNS / IPv4 / IPv6"))
        add(routes, t("Маршруты Android VPN", 18f, white, true), 8)
        val routeFacts = currentRouteFacts()
        val routeAssessment = VpnRouteAdvisor.assess(connectionActive, routeFacts)
        val routeTitle = if (routeScanRunning) "Проверяем Android…" else routeAssessment.title
        add(routes, t(routeTitle, 14f, white, true), 9)
        add(routes, t(routeAssessment.explanation, 12f,
            if (routeAssessment.needsReview) errorColor else grey), 8)
        if (routeFacts != null) {
            fun yn(flag: Boolean?): String = when (flag) {
                true -> "да"
                false -> "нет"
                null -> "неизвестно"
            }
            add(routes, t(
                "VPN-сеть: " + yn(routeFacts.visible) +
                    " · полный IPv4-маршрут: " + yn(routeFacts.ipv4DefaultRoute) +
                    " · полный IPv6-маршрут: " + yn(routeFacts.ipv6DefaultRoute) +
                    " · DNS настроен: " + yn(routeFacts.dnsConfigured),
                12f, teal
            ), 10)
        }
        val inspect = action(if (routeScanRunning) "Проверка…" else
            "Проверить маршруты и DNS")
        inspect.isEnabled = !routeScanRunning && connectionActive &&
            VainahVpnService.runningInProcess
        add(routes, inspect, 12)
        inspect.setOnClickListener { inspectVpnRoutes() }
        add(routes, t(
            "Это локальная проверка таблицы маршрутов и настройки DNS. " +
                "Она не отправляет интернет-запросы, не измеряет DNS-утечки " +
                "и не подтверждает внешний IP. Результат может устареть после смены сети.",
            12f, grey
        ), 9)

        val handoffs = VpnUnderlayStatus.history(this)
        val historyCard = card()
        add(body, historyCard, 16)
        add(historyCard, tag("ПЕРЕКЛЮЧЕНИЯ СЕТИ"))
        add(historyCard, t("История за текущий VPN-сеанс", 18f, white, true), 8)
        add(historyCard, t(
            "Только тип сети и состояние проверки Android. " +
                "Не подтверждает, что сайты открывались через VPN после перехода.",
            12f, grey), 8)
        fun transportLabel(code: String): String = when (code) {
            "wifi" -> "Wi-Fi"
            "cellular" -> "4G/5G"
            "ethernet" -> "Ethernet"
            "none" -> "нет сети"
            else -> "другая сеть"
        }
        if (handoffs.isEmpty()) {
            add(historyCard, t("Переходы пока не зафиксированы.", 12f, grey), 9)
        } else {
            for (event in handoffs.takeLast(6).asReversed()) {
                val line = transportLabel(event.from) + " → " +
                    transportLabel(event.to) + " · " +
                    (if (event.validated) "Android подтвердил сеть"
                     else "доступ сети не подтверждён")
                add(historyCard, t(line, 12f, grey), 9)
            }
            if (handoffs.size > 6) {
                add(historyCard, t(
                    "Остальные события включены в обезличенный отчёт.",
                    12f, grey
                ), 8)
            }
        }
        val refreshHistory = action("Обновить историю сети")
        add(historyCard, refreshHistory, 11)
        refreshHistory.setOnClickListener { render() }

        val report = action("Скопировать безопасный отчёт")
        add(info, report, 12)
        report.setOnClickListener {
            val diag = getSharedPreferences("vpn_diagnostics", MODE_PRIVATE)
            val state = VpnConnectionState.read(this)
            val underlay = VpnUnderlayStatus.read(this)
            val text = VpnDiagnosticReport.create(
                state.phase,
                diag.getString("last_stage", null),
                diag.getString("vpn_probe_reason", null),
                Build.VERSION.SDK_INT,
                VainahVpnService.runningInProcess,
                networkFacts = currentRouteFacts(),
                underlay = VpnUnderlayFacts(
                    transport = underlay.transport,
                    validated = underlay.validated,
                    transitions = underlay.transitions,
                ),
                handoffEvents = VpnUnderlayStatus.history(this),
                recoveryCode = VpnUnderlayStatus.recovery(
                    this, state.canDisconnect && VainahVpnService.runningInProcess
                ).code,
                failureCode = if (state.phase == VpnConnectionState.FAILED)
                    diag.getString("last_failure_code", null) else null,
            )
            val clipboard = getSystemService(CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText("Vainah VPN diagnostic", text))
            popup("Обезличенный отчёт скопирован. В нём нет VPN-ключей или адресов серверов.")
        }
        val retry = action("Обновить серверы")
        add(info, retry, 12)
        retry.setOnClickListener { page = Page.HOME; render(); refreshServers(true) }
    }

    private fun currentRouteFacts(): VpnNetworkFacts? {
        val state = VpnConnectionState.read(this)
        if (!state.canDisconnect || !VainahVpnService.runningInProcess) return null
        if (state != routeConnectionSnapshot ||
            VpnUnderlayStatus.read(this) != routeNetworkSnapshot) return null
        return routeSnapshot
    }

    private fun inspectVpnRoutes() {
        if (routeScanRunning) return
        val before = VpnConnectionState.read(this)
        if (!before.canDisconnect || !VainahVpnService.runningInProcess) {
            popup("Сначала запусти Vainah VPN для проверки маршрутов.")
            return
        }
        val physicalBefore = VpnUnderlayStatus.read(this)
        val request = ++routeScanVersion
        routeScanRunning = true
        routeSnapshot = null
        render()
        Thread({
            val observed = VpnConnectivity.androidVpnFacts(this)
            main.post {
                if (request != routeScanVersion || isFinishing || isDestroyed) return@post
                routeScanRunning = false
                val now = VpnConnectionState.read(this)
                val physicalNow = VpnUnderlayStatus.read(this)
                if (now != before || physicalNow != physicalBefore ||
                    !VainahVpnService.runningInProcess
                ) {
                    routeSnapshot = null
                    routeNetworkSnapshot = null
                    routeConnectionSnapshot = null
                    popup("Состояние VPN или сети изменилось. Повтори проверку маршрутов.")
                } else {
                    routeSnapshot = observed
                    routeConnectionSnapshot = now
                    routeNetworkSnapshot = physicalNow
                }
                if (page == Page.DIAGNOSTICS) render()
            }
        }, "vainah-local-vpn-route-inspection").start()
    }


    // Each screen reads actual subscription/service state; no invented ping,
    // traffic numbers, expiry dates or subscription-device limits.
    private fun locations(body: LinearLayout) {
        val locationCard = card()
        add(body, locationCard, 21)
        add(locationCard, tag("Локации из подписки"))
        add(locationCard, t("Доступные серверы", 20f, white, true), 9)
        add(locationCard, t(source.sourceLabel(), 12f, grey), 9)
        add(locationCard, t(if (nodes.isEmpty()) "Нет загруженных серверов." else
            cacheMessage, 12f, grey), 8)
        lastError?.let { add(locationCard, t(it, 12f, errorColor), 9) }
        if (nodes.isEmpty()) {
            add(locationCard, t(
                "Добавь HTTPS-подписку или VLESS-ключ. Локации, названия " +
                    "и доступность не подменяются демоданными.", 13f, grey), 13)
        }
        for ((index, node) in nodes.withIndex()) {
            val observation = serverProbes.firstOrNull { it.index == index }
            val latency = observation?.takeIf { it.successes >= 2 }?.medianMs
            val suffix = when {
                latency != null -> " · TCP " + latency + " мс"
                observation != null -> " · TCP недоступен/не измерен"
                else -> ""
            }
            val choose = action(
                (if (node.uri == selected?.uri) "✓  " else "") + node.label + suffix)
            add(locationCard, choose, 8)
            choose.setOnClickListener {
                selected = node
                page = Page.HOME
                render()
            }
        }
        val refresh = action(if (source.busy) "Обновление…" else "Обновить локации", true)
        refresh.isEnabled = !source.busy
        add(locationCard, refresh, 17)
        refresh.setOnClickListener { refreshServers(true) }
        val import = action("Добавить подписку")
        add(locationCard, import, 9)
        import.setOnClickListener { page = Page.ACCOUNT; render() }

        val note = card()
        add(body, note, 15)
        add(note, tag("TCP-задержка входных серверов"))
        add(note, t(serverProbeMessage, 15f, white, true), 10)
        add(note, t(
            "Измеряется физическое TCP-соединение до узла: не VPN-пинг, " +
                "не задержка REALITY, не нагрузка сервера и не гарантия подключения. " +
                "Замеры выполняются без активного VPN после нажатия кнопки. " +
                "Проверяются первые " + ServerTcpSelector.MAX_PROBED_NODES + " локаций.",
            12f, grey), 9)
        val probe = action(if (serverProbeRunning) "Проверяем TCP…" else
            "Измерить и выбрать самый быстрый по TCP", true)
        probe.isEnabled = nodes.isNotEmpty() && !serverProbeRunning &&
            !VpnConnectionState.read(this).canDisconnect
        add(note, probe, 13)
        probe.setOnClickListener { probeServersAndChoose() }
    }

    private fun invalidateServerProbes() {
        serverProbeGeneration++
        serverProbeRunning = false
        serverProbes = emptyList()
        serverProbeMessage = "TCP-задержка входных узлов ещё не измерялась."
    }

    private fun probeServersAndChoose() {
        if (serverProbeRunning) return
        if (VpnConnectionState.read(this).canDisconnect) {
            popup("Для корректной проверки сначала отключи VPN.")
            return
        }
        val capture = nodes.take(ServerTcpSelector.MAX_PROBED_NODES).toList()
        if (capture.isEmpty()) {
            popup("Сначала добавь и обнови подписку.")
            return
        }
        serverProbeRunning = true
        val version = ++serverProbeGeneration
        val selectedBefore = selected?.uri
        serverProbeMessage = "Проверяем TCP-подключение к узлам…"
        render()
        Thread({
            val measured = capture.mapIndexed { index, node ->
                ServerTcpMeasurement.sample(node).copy(index = index)
            }
            main.post {
                if (version != serverProbeGeneration || isFinishing || isDestroyed)
                    return@post
                serverProbeRunning = false
                val unchanged = capture == nodes.take(capture.size) &&
                    source.savedLink() != null
                if (!unchanged) {
                    serverProbes = emptyList()
                    serverProbeMessage = "Список серверов изменился. Повтори замер."
                } else if (VpnConnectionState.read(this).canDisconnect) {
                    serverProbes = emptyList()
                    serverProbeMessage = "VPN подключён во время замера. Данные сброшены."
                } else {
                    serverProbes = measured
                    val best = ServerTcpSelector.best(measured)
                    if (best == null) {
                        serverProbeMessage = "Нет двух успешных TCP-замеров для выбора."
                    } else {
                        val chosen = capture[best]
                        val latency = measured[best].medianMs
                        if (selected?.uri == selectedBefore) {
                            selected = nodes.firstOrNull { it.uri == chosen.uri } ?: selected
                            serverProbeMessage = "Выбран " + chosen.label + " · TCP " +
                                latency + " мс. Нажми «Подключиться», чтобы проверить VPN."
                        } else {
                            serverProbeMessage = "Замер завершён · лучший TCP " +
                                latency + " мс. Твой ручной выбор сохранён."
                        }
                    }
                }
                render()
            }
        }, "vainah-tcp-entry-probe").start()
    }

    private fun devices(body: LinearLayout) {
        val deviceCard = card()
        add(body, deviceCard, 21)
        add(deviceCard, tag("Устройства"))
        add(deviceCard, t("Этот Android", 19f, white, true), 9)
        add(deviceCard, t("Android " + Build.VERSION.RELEASE +
            " · " + android.os.Build.MANUFACTURER, 12f, grey), 10)
        add(deviceCard, t("Список привязанных устройств и лимиты из H1Cloud " +
            "появятся только после авторизованной синхронизации. " +
            "Данные аккаунта здесь не выдумываются.", 12f, grey), 12)
        val details = card()
        add(body, details, 15)
        add(details, tag("Платформы"))
        for (platform in listOf(
            "Android · libbox / VpnService",
            "Windows · отдельный туннель",
            "macOS · нативный сетевой модуль",
            "iOS / iPadOS · Network Extension")) {
            add(details, t("•  " + platform, 13f, grey), 11)
        }
        add(details, t("Сборки других платформ ещё не опубликованы.", 12f, teal), 14)
    }

    private fun security(body: LinearLayout) {
        val protection = card()
        add(body, protection, 21)
        add(protection, tag("Контроль безопасности"))
        add(protection, t("Только проверенные состояния", 19f, white, true), 9)
        val snapshot = VpnConnectionState.read(this)
        add(protection, t(
            if (snapshot.canDisconnect) "Туннель запущен; защита трафика не подтверждена."
            else "Нет подтверждённого VPN-соединения.", 13f,
            if (snapshot.canDisconnect) teal else grey), 12)
        for (note in listOf(
            "✓  Конфигурации сохраняются в Android Keystore",
            "✓  TLS-проверка подписки не отключается",
            "•  DNS/IPv6-утечки не проверены на этом устройстве",
            "•  Приложение не заявляет об анонимности без тестов")) {
            add(protection, t(note, 12f, grey), 11)
        }

        val kill = card()
        add(body, kill, 16)
        add(kill, tag("KILL SWITCH / ANDROID"))
        add(kill, t("Блокировать интернет без VPN", 18f, white, true), 8)
        add(kill, t(
            "Это системная защита Android, а не выключатель на сайте. " +
                "Открой настройки VPN, выбери Vainah VPN Next, включи " +
                "«Всегда включён VPN», затем «Блокировать подключения без VPN». " +
                "Если VPN отключится, Android будет блокировать подключения без него.",
            12f, grey), 9)
        add(kill, t(
            "Важно: исключённые приложения при системной блокировке обхода " +
                "не смогут использовать сеть напрямую. Режимы несовместимы.",
            12f, errorColor), 12)
        val openSettings = action("Открыть системные настройки VPN")
        add(kill, openSettings, 13)
        openSettings.setOnClickListener {
            try {
                startActivity(Intent(Settings.ACTION_VPN_SETTINGS))
            } catch (_: android.content.ActivityNotFoundException) {
                startActivity(Intent(Settings.ACTION_SETTINGS))
            }
        }

        val split = card()
        add(body, split, 16)
        add(split, tag("SPLIT TUNNELING / ANDROID"))
        add(split, t("Приложения вне VPN", 18f, white, true), 9)
        val excluded = SplitTunnelPreferences.read(this)
        add(split, t(
            if (excluded.isEmpty()) "Исключений нет: приложения работают через VPN."
            else "Исключений выбрано: " + excluded.size +
                ". Изменения применятся при следующем подключении.",
            12f, if (excluded.isEmpty()) grey else errorColor), 9)
        add(split, t(
            "Исключённые приложения используют обычный интернет без VPN. " +
                "Никогда не включай этот режим, если хочешь направить " +
                "весь трафик через VPN. При системном Kill Switch исключения игнорируются.",
            12f, grey), 8)
        if (!BuildConfig.VAINAH_LIBBOX_ENABLED) {
            add(split, t(
                "В этой preview-сборке libbox-туннель отключён, " +
                    "поэтому раздел только информационный.",
                12f, errorColor), 12)
        }
        val manageSplit = action("Выбрать исключённые приложения")
        manageSplit.isEnabled = BuildConfig.VAINAH_LIBBOX_ENABLED
        add(split, manageSplit, 12)
        manageSplit.setOnClickListener { editSplitTunnelApps() }

        val diag = action("Открыть диагностику")
        add(protection, diag, 17)
        diag.setOnClickListener { page = Page.DIAGNOSTICS; render() }
    }

    private fun editSplitTunnelApps() {
        if (!BuildConfig.VAINAH_LIBBOX_ENABLED) {
            popup("Требуется реальная сборка с libbox. Preview не меняет VPN.")
            return
        }
        if (VpnConnectionState.read(this).canDisconnect) {
            popup("Сначала отключи VPN. Split Tunneling меняется только перед новым подключением.")
            return
        }
        val launcher = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val applications = packageManager.queryIntentActivities(launcher, 0)
            .mapNotNull { info ->
                val packageName = info.activityInfo?.packageName ?: return@mapNotNull null
                if (packageName == packageNameForThisApp() ||
                    SplitTunnelPolicy.normalize(listOf(packageName), packageNameForThisApp()).isEmpty()
                ) return@mapNotNull null
                packageName to info.loadLabel(packageManager).toString()
            }
            .distinctBy { it.first }
            .sortedWith(compareBy<Pair<String, String>> { it.second.lowercase() }
                .thenBy { it.first })
        if (applications.isEmpty()) {
            popup("Android не предоставил список установленных приложений.")
            return
        }
        val old = SplitTunnelPreferences.read(this)
        val chosen = old.toMutableSet()
        val labels = applications.map { it.second + " (" + it.first + ")" }.toTypedArray()
        val checked = applications.map { it.first in old }.toBooleanArray()
        AlertDialog.Builder(this)
            .setTitle("Приложения вне VPN")
            .setMessage("Выбранные программы будут использовать интернет напрямую, " +
                "не через Vainah VPN. Не совмещай с режимом блокировки без VPN.")
            .setMultiChoiceItems(labels, checked) { _, index, enabled ->
                val name = applications[index].first
                if (enabled) {
                    if (chosen.size < SplitTunnelPolicy.MAX_EXCLUDED_APPS) chosen.add(name)
                    else popup("Не более " + SplitTunnelPolicy.MAX_EXCLUDED_APPS + " исключений.")
                } else chosen.remove(name)
            }
            .setNegativeButton("Отмена", null)
            .setNeutralButton("Сбросить исключения") { _, _ ->
                if (VpnConnectionState.read(this).canDisconnect) {
                    popup("Отключи VPN перед изменением списка.")
                } else if (!SplitTunnelPreferences.save(this, emptySet())) {
                    popup("Не удалось сохранить настройки.")
                } else render()
            }
            .setPositiveButton("Сохранить") { _, _ ->
                if (VpnConnectionState.read(this).canDisconnect) {
                    popup("Отключи VPN перед изменением списка.")
                } else if (chosen.size > SplitTunnelPolicy.MAX_EXCLUDED_APPS ||
                    !SplitTunnelPreferences.save(this, chosen)) {
                    popup("Не удалось сохранить настройки.")
                } else {
                    render()
                    popup("Изменения вступят в силу при следующем подключении VPN. " +
                        "В режиме системной блокировки обхода исключения не применяются.")
                }
            }
            .show()
    }

    private fun packageNameForThisApp(): String = packageName

    private fun settings(body: LinearLayout) {
        val preferences = card()
        add(body, preferences, 21)
        add(preferences, tag("Настройки подключения"))
        add(preferences, t("Параметры Vainah Next", 19f, white, true), 8)
        add(preferences, t(
            "При смене Wi-Fi/4G/5G libbox получает обновление физического " +
                "интерфейса. Бесшовность соединения ещё требует испытаний " +
                "на телефоне; Kill Switch включается в настройках Android.",
            12f, grey), 11)
        val subscriptionButton = action("Управление подпиской")
        add(preferences, subscriptionButton, 14)
        subscriptionButton.setOnClickListener { page = Page.ACCOUNT; render() }
        val safe = action("Диагностика DNS, HTTPS и туннеля")
        add(preferences, safe, 9)
        safe.setOnClickListener { page = Page.DIAGNOSTICS; render() }
        val privacy = action("Настройки безопасности")
        add(preferences, privacy, 9)
        privacy.setOnClickListener { page = Page.SECURITY; render() }

        val version = card()
        add(body, version, 15)
        add(version, tag("О приложении"))
        add(version, t("Vainah VPN Next " + BuildConfig.VERSION_NAME,
            16f, white, true), 9)
        add(version, t("Тестовая сборка. Приложение не связано с " +
            "действующей оплатой. Не заменяет проверку реального VPN на Android.",
            12f, grey), 10)
    }

    private fun more(body: LinearLayout) {
        val hub = card()
        add(body, hub, 21)
        add(hub, tag("VAINAH NEXT / РАЗДЕЛЫ"))
        add(hub, t("Все инструменты в одном месте", 19f, white, true), 10)
        add(hub, t("Настройки, устройства и информация о безопасности.",
            12f, grey), 8)
        for ((target, label) in listOf(
            Page.DEVICES to "Мои устройства",
            Page.DIAGNOSTICS to "Диагностика соединения",
            Page.SECURITY to "Безопасность и приватность",
            Page.SETTINGS to "Настройки приложения",
            Page.ACCOUNT to "Подписка и вход")) {
            val button = action(label)
            add(hub, button, 10)
            button.setOnClickListener { page = target; render() }
        }
    }

    private fun refreshServers(manual: Boolean) {
        if (source.savedLink() == null) {
            if (manual) popup("Сначала сохрани VPN-профиль.")
            return
        }
        if (!manual && VpnConnectionState.read(this).canDisconnect) return
        nextAutoRefresh = SystemClock.elapsedRealtime() +
            SubscriptionRefreshPolicy.NORMAL_MS
        val started = source.refresh { result ->
            result.onSuccess { fresh ->
                invalidateServerProbes()
                nodes = ServerListReconciler.unique(fresh)
                selected = ServerListReconciler.preserve(selected, nodes)
                    ?: nodes.firstOrNull()
                lastError = null
                cacheMessage = "Загружено серверов: " + nodes.size
                nextAutoRefresh = SystemClock.elapsedRealtime() +
                    SubscriptionRefreshPolicy.NORMAL_MS
            }.onFailure { ex ->
                lastError = SubscriptionLoadFailure.explain(ex)
                cacheMessage = if (nodes.isNotEmpty())
                    "Сохранённый список; актуальность не подтверждена"
                else "Серверы не загрузились"
                nextAutoRefresh = SubscriptionRefreshPolicy.nextAllowed(
                    SystemClock.elapsedRealtime(), ex)
            }
            if (!isFinishing && !isDestroyed) render()
        }
        if (started && page == Page.HOME) render()
    }

    private fun maybeRefresh() {
        if (page != Page.HOME || source.busy) return
        val link = source.savedLink() ?: return
        if (SubscriptionRefreshPolicy.shouldAutoRefresh(
                SystemClock.elapsedRealtime(), nextAutoRefresh,
                VpnConnectionState.read(this).canDisconnect,
                SubscriptionInput.isDirectKey(link)))
            refreshServers(false)
    }

    private fun connect() {
        if (VpnConnectionState.read(this).canDisconnect) { disconnect(); return }
        if (!EngineRegistry.active.ready) {
            popup("VPN-движок libbox не установлен. Трафик не защищён.")
            return
        }
        val node = selected ?: run { popup("Сначала выбери сервер."); return }
        if (source.savedLink() == null) { popup("Добавь подписку."); return }
        pendingNode = node
        val permission = VpnService.prepare(this)
        if (permission == null) launchTunnel()
        else startActivityForResult(permission, vpnConsentCode)
    }
    @Deprecated("Android VpnService consent callback")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == vpnConsentCode) {
            if (resultCode == RESULT_OK) launchTunnel()
            else { pendingNode = null; popup("Разрешение VPN не предоставлено.") }
        }
    }
    private fun launchTunnel() {
        val node = pendingNode ?: return
        pendingNode = null
        if (!EngineRegistry.active.ready || source.savedLink() == null) return
        val intent = Intent(this, VainahVpnService::class.java).apply {
            action = VainahVpnService.ACTION_CONNECT
            putExtra(VainahVpnService.EXTRA_SELECTED_VLESS, node.uri)
            putExtra(VainahVpnService.EXTRA_SELECTED_LABEL, node.label)
        }
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent)
        else startService(intent)
        main.postDelayed({ updateConnection() }, 450)
    }
    private fun disconnect() {
        startService(Intent(this, VainahVpnService::class.java).apply {
            action = VainahVpnService.ACTION_DISCONNECT
        })
        main.postDelayed({ updateConnection() }, 350)
    }
    private fun updateConnection() {
        val snapshot = VpnConnectionState.read(this)
        val connected = snapshot.canDisconnect
        stateView?.text = when (snapshot.phase) {
            VpnConnectionState.ONLINE -> "Туннель запущен"
            VpnConnectionState.TUN_READY -> "VPN-туннель активен"
            VpnConnectionState.STARTING -> "Подключение…"
            VpnConnectionState.FAILED -> "Ошибка подключения"
            else -> "Не подключено"
        }
        stateView?.setTextColor(if (connected) green else white)
        detailView?.text = if (snapshot.phase == VpnConnectionState.OFF)
            "Выбери локацию и проверь IP в браузере после подключения."
        else snapshot.detail.ifBlank { "Данные службы пока недоступны." }
        connectView?.text = if (connected) "Отключить VPN" else "Подключиться"
        trafficView?.text = if (!connected) "Статистика появится после подключения."
        else VpnTrafficStore.read(this)?.let {
            "↓ " + VpnTrafficStore.format(it.downlink) + "/с · ↑ " +
                VpnTrafficStore.format(it.uplink) + "/с\\nЗа сеанс: ↓ " +
                VpnTrafficStore.format(it.downlinkTotal) + " · ↑ " +
                VpnTrafficStore.format(it.uplinkTotal)
        } ?: "Счётчики libbox пока недоступны"
    }
}
