package app.vainah.vpn

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/**
 * Vainah VPN Next. No fake VPN status, embedded billing, WebView or hard-coded
 * Netlify dependency. Subscription fetching lives in SubscriptionController;
 * VainahVpnService exclusively owns the real libbox VPN session.
 */
class MainActivity : Activity() {
    private enum class Page { HOME, ACCOUNT, HELP }
    private var page = Page.HOME
    private lateinit var source: SubscriptionController
    private var nodes: List<VainahNode> = emptyList()
    private var selected: VainahNode? = null
    private var pendingNode: VainahNode? = null
    private var lastError: String? = null
    private var cacheMessage = "Серверы ещё не обновлены"
    private var nextAutoRefresh = 0L
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
        main.removeCallbacks(ticker)
        main.post(ticker)
    }
    override fun onPause() {
        main.removeCallbacks(ticker)
        super.onPause()
    }
    override fun onDestroy() {
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
        val frame = column().apply { setBackgroundColor(bg) }
        val scroll = ScrollView(this).apply { isFillViewport = true }
        val body = column().apply {
            setPadding(dp(20), dp(28), dp(20), dp(28))
        }
        scroll.addView(body)
        frame.addView(scroll, LinearLayout.LayoutParams(-1, 0, 1f))
        add(body, tag("VAINAH VPN / NEXT"))
        add(body, t(when (page) {
            Page.HOME -> "Твоё соединение. Твои правила."
            Page.ACCOUNT -> "Мой VPN"
            Page.HELP -> "Диагностика"
        }, 25f, white, true), 8)
        add(body, t("Android · " + BuildConfig.VERSION_NAME, 12f, grey), 7)
        when (page) {
            Page.HOME -> home(body)
            Page.ACCOUNT -> account(body)
            Page.HELP -> help(body)
        }
        val nav = horizontal().apply {
            setBackgroundColor(card)
            setPadding(dp(12), dp(9), dp(12), dp(9))
        }
        for ((target, label) in listOf(
            Page.HOME to "Главная", Page.ACCOUNT to "Мой VPN",
            Page.HELP to "Помощь"
        )) {
            val button = action(label, target == page).apply {
                minHeight = dp(44)
                textSize = 12f
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
        val retry = action("Обновить серверы")
        add(info, retry, 12)
        retry.setOnClickListener { page = Page.HOME; render(); refreshServers(true) }
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
