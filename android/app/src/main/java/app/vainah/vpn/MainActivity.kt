package app.vainah.vpn

import android.app.Activity
import android.animation.ValueAnimator
import android.content.res.ColorStateList
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.net.Uri
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
import android.text.Editable
import android.text.TextWatcher
import android.text.InputType
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.util.concurrent.Executors
import java.util.concurrent.ExecutorService
import java.util.concurrent.Callable

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
    private var lastCacheCheckElapsedMs = 0L
    private var serverProbeRunning = false
    private var serverProbeAttempted = false
    private var activeProbePool: ExecutorService? = null
    private var serverProbeGeneration = 0
    private var serverProbeMessage = "TCP-задержка входных узлов ещё не измерялась."
    private var serverProbes: List<ServerTcpObservation> = emptyList()
    private var serverListExpanded = false
    private var contentScroll: ScrollView? = null
    private var lastRenderedPage: Page? = null
    private var showAdvancedDiagnostics = false
    private var serverSearchQuery = ""
    private var showFavoriteServers = false
    private var serverCollection = ServerCollection.ALL
    private var serverSort = ServerSort.SUBSCRIPTION
    private var routeScanVersion = 0
    private var routeScanRunning = false
    private var routeSnapshot: VpnNetworkFacts? = null
    private var routeNetworkSnapshot: VpnUnderlayStatus.Snapshot? = null
    private var routeConnectionSnapshot: VpnConnectionState.Snapshot? = null
    private var stateView: TextView? = null
    private var detailView: TextView? = null
    private var trafficView: TextView? = null
    private var trafficChart: TrafficSparklineView? = null
    private var networkStatusView: TextView? = null
    private val trafficTimeline = TrafficTimeline()
    private var connectView: Button? = null
    private var powerOrb: View? = null
    private var pulseAnimator: ValueAnimator? = null
    private val main = Handler(Looper.getMainLooper())
    private val vpnConsentCode = 7041

    private val bg = VainahDesign.background
    private val card = VainahDesign.surface2
    private val border = VainahDesign.border
    private val violet = VainahDesign.purple
    private val white = VainahDesign.ink
    private val grey = VainahDesign.muted
    private val teal = VainahDesign.sky
    private val green = VainahDesign.green
    private val errorColor = VainahDesign.error

    private val ticker = object : Runnable {
        override fun run() {
            updateConnection()
            reloadBackgroundSubscription()
            maybeRefresh()
            main.postDelayed(this, 2300)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = bg
        window.navigationBarColor = bg
        // The new light theme needs dark system bar icons on Android 8+.
        window.decorView.systemUiVisibility = if (VainahTheme.isDark) 0 else
            View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or
                View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
        source = SubscriptionController(this)
        page = savedInstanceState?.getString("page")?.let {
            runCatching { Page.valueOf(it) }.getOrNull()
        } ?: Page.HOME
        nodes = source.cachedNodes()
        selected = nodes.firstOrNull { SubscriptionNodeSupport.canConnect(it.uri) }
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
        lastCacheCheckElapsedMs = 0L
        reloadBackgroundSubscription()
        // A killed Android process cannot preserve the old VPN owner. Never
        // show a stale "active tunnel" after service/process restart.
        if (VpnConnectionState.read(this).phase in setOf(
                VpnConnectionState.TUN_READY, VpnConnectionState.ONLINE
            ) && !VainahVpnService.runningInProcess) {
            VpnConnectionState.failed(this,
                "VPN-служба не запущена; проверь подключение перед использованием.")
        }
        main.removeCallbacks(ticker)
        main.post(ticker)
    }
    override fun onPause() {
        main.removeCallbacks(ticker)
        pulseAnimator?.cancel()
        pulseAnimator = null
        super.onPause()
    }
    override fun onDestroy() {
        routeScanVersion++
        invalidateServerProbes()
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
        background = VainahUi.cardBackground(this@MainActivity)
        setPadding(dp(17), dp(17), dp(17), dp(18))
        elevation = dp(3).toFloat()
    }
    private fun tag(value: String) = t(value.uppercase(), 11f, violet, true).apply {
        letterSpacing = 0.1f
    }
    private fun action(value: String, mainButton: Boolean = false) = Button(this).apply {
        text = value
        isAllCaps = false
        textSize = 13f
        minHeight = dp(46)
        setPadding(dp(10), 0, dp(10), 0)
        typeface = Typeface.create("sans-serif-medium", Typeface.BOLD)
        setTextColor(if (mainButton) Color.WHITE else white)
        background = VainahUi.buttonBackground(this@MainActivity, mainButton)
    }
    private fun input(hintValue: String) = EditText(this).apply {
        hint = hintValue
        setSingleLine(true)
        textSize = 13f
        setTextColor(white)
        setHintTextColor(grey)
        setPadding(dp(13), dp(14), dp(13), dp(14))
        background = shape(VainahDesign.surface, border, 12)
        importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO
    }
    private fun popup(message: String) {
        // Branded, accessible dialog instead of a wall of system-default text.
        // The message is already credential-safe before reaching this method.
        val dialog = AlertDialog.Builder(this).create()
        val surface = column().apply {
            background = VainahUi.cardBackground(this@MainActivity)
            setPadding(dp(20), dp(20), dp(20), dp(17))
        }
        add(surface, tag("VAINAHVPN"))
        add(surface, t(message, 13.5f, white), 11)
        val close = action("Понятно", true)
        add(surface, close, 17)
        close.setOnClickListener { dialog.dismiss() }
        dialog.setView(surface)
        dialog.setOnShowListener {
            dialog.window?.setBackgroundDrawable(
                android.graphics.drawable.ColorDrawable(Color.TRANSPARENT)
            )
            dialog.window?.setLayout(
                (resources.displayMetrics.widthPixels * 0.89f).toInt(),
                android.view.WindowManager.LayoutParams.WRAP_CONTENT
            )
        }
        dialog.show()
    }

    /** Native account and tariffs. Only the selected checkout opens a site. */
    private fun openNativeCabinet(tab: String = "cabinet") {
        startActivity(Intent(this, NativeCabinetActivity::class.java)
            .putExtra("page", if (tab == "plans") "plans" else "cabinet"))
    }

    private fun openOfficialPage(page: String) {
        // Keep existing internal buttons, but remove external account routing.
        openNativeCabinet(if (page == "plans.html") "plans" else "cabinet")
    }

    private fun render() {
        pulseAnimator?.cancel()
        pulseAnimator = null
        powerOrb = null
        stateView = null
        detailView = null
        trafficView = null
        trafficChart = null
        networkStatusView = null
        connectView = null
        // Every page shares the same clean light surface and typography.
        val light = !VainahTheme.isDark
        val lastOffset = if (lastRenderedPage == page) contentScroll?.scrollY ?: 0 else 0
        val frame = column().apply {
            background = VainahUi.pageBackground()
            // Android 15+ draws behind system bars. Keep the top brand and
            // bottom navigation outside status/gesture areas on every device.
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                setOnApplyWindowInsetsListener { view, insets ->
                    val bars = insets.getInsets(android.view.WindowInsets.Type.systemBars())
                    view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
                    insets
                }
            } else {
                fitsSystemWindows = true
            }
        }
        val scroll = ScrollView(this).apply { isFillViewport = true }
        val body = column().apply {
            setPadding(dp(15), dp(12), dp(15), dp(23))
        }
        scroll.addView(body)
        frame.addView(scroll, LinearLayout.LayoutParams(-1, 0, 1f))
        if (page != Page.HOME) {
            val brand = horizontal().apply { setPadding(dp(4), 0, dp(4), 0) }
            brand.addView(VainahShieldView(this),
                LinearLayout.LayoutParams(dp(35), dp(35)))
            brand.addView(t("VAINAH", 16f, white, true),
                LinearLayout.LayoutParams(-2, -2).apply { marginStart = dp(8) })
            brand.addView(t("VPN", 16f, violet, true))
            add(body, brand, 3)
            add(body, t(when (page) {
                Page.HOME -> "VainahVPN"
                Page.LOCATIONS -> "Серверы"
                Page.ACCOUNT -> "Подписка"
                Page.DEVICES -> "Мои устройства"
                Page.DIAGNOSTICS -> "Диагностика"
                Page.SECURITY -> "Защита"
                Page.SETTINGS -> "Настройки"
                Page.MORE -> "Профиль"
            }, 27f, white, true), 12)
        }
        if (!light) add(body, t("Android · " + BuildConfig.VERSION_NAME, 12f,
            grey), 7)
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
            background = GradientDrawable(
                GradientDrawable.Orientation.TOP_BOTTOM,
                intArrayOf(VainahDesign.surface, VainahDesign.surface2)
            ).apply { setStroke(dp(1), VainahDesign.border) }
            elevation = dp(7).toFloat()
            setPadding(dp(6), dp(7), dp(6), dp(6))
        }
        val selectedTab = if (page in listOf(Page.DEVICES, Page.DIAGNOSTICS,
                Page.SETTINGS)) Page.MORE else page
        for ((target, label) in listOf(
            Page.HOME to "Главная", Page.LOCATIONS to "Серверы",
            Page.SECURITY to "Защита", Page.ACCOUNT to "Подписка",
            Page.MORE to "Кабинет"
        )) {
            val active = target == selectedTab
            val tab = column().apply {
                gravity = Gravity.CENTER
                isClickable = true
                isFocusable = true
                contentDescription = label
                val fill = GradientDrawable().apply {
                    setColor(if (active) VainahDesign.inactive else VainahDesign.surface)
                    cornerRadius = dp(15).toFloat()
                }
                background = RippleDrawable(
                    ColorStateList.valueOf(Color.argb(60, 180, 151, 255)),
                    fill, null
                )
                val glyph = NavigationGlyphView(this@MainActivity, target.name, active)
                addView(glyph, LinearLayout.LayoutParams(dp(22), dp(22)))
                addView(t(label, 10f, if (active) violet else grey, active).apply {
                    gravity = Gravity.CENTER
                    maxLines = 1
                }, LinearLayout.LayoutParams(-1, -2).apply {
                    topMargin = dp(3)
                })
                setOnClickListener {
                    if (target == Page.MORE) {
                        openNativeCabinet()
                    } else if (target != page) {
                        page = target
                        render()
                    }
                }
            }
            nav.addView(tab, LinearLayout.LayoutParams(0, dp(55), 1f).apply {
                marginStart = dp(2)
                marginEnd = dp(2)
            })
        }
        frame.addView(nav)
        setContentView(frame)
        contentScroll = scroll
        lastRenderedPage = page
        if (lastOffset > 0) scroll.post { scroll.scrollTo(0, lastOffset) }
        updateConnection()
        // One automatic real TCP scan per loaded list, never a fake ping.
        // It is not used to replace a manual server selection.
        if ((page == Page.HOME || page == Page.LOCATIONS) &&
            !serverProbeAttempted && !serverProbeRunning &&
            nodes.isNotEmpty() && source.savedLink() != null &&
            !VpnConnectionState.read(this).canDisconnect) {
            serverProbeAttempted = true
            main.post {
                if (!isFinishing && !isDestroyed && !serverProbeRunning &&
                    !VpnConnectionState.read(this).canDisconnect) {
                    probeServersAndChoose(selectBest = false)
                }
            }
        }
    }

    /** Shared compact settings/profile row instead of stacked giant buttons. */
    private fun menuRow(
        label: String,
        description: String? = null,
        onOpen: () -> Unit
    ): View {
        val item = horizontal().apply {
            minimumHeight = dp(if (description == null) 54 else 61)
            setPadding(dp(11), dp(8), dp(11), dp(8))
            background = VainahUi.buttonBackground(this@MainActivity, false)
            isClickable = true
            isFocusable = true
            contentDescription = label
            setOnClickListener { onOpen() }
        }
        val labels = column()
        add(labels, t(label, 13.5f, white, true))
        if (description != null) add(labels, t(description, 10.5f, grey), 3)
        item.addView(labels, LinearLayout.LayoutParams(0, -2, 1f))
        item.addView(t("›", 22f, grey).apply {
            gravity = Gravity.CENTER
        }, LinearLayout.LayoutParams(dp(20), dp(34)))
        return item
    }

    private fun lightAction(label: String): Button = action(label).apply {
        background = VainahUi.buttonBackground(this@MainActivity, false)
        setTextColor(ServerListVisual.textColor())
        minHeight = dp(42)
    }

    private fun directory(
        query: String = "",
        favoriteOnly: Boolean = false,
        sort: ServerSort = ServerSort.SUBSCRIPTION,
    ): List<ServerDirectoryEntry> = ServerDirectory.view(
        nodes, source.favoriteNodeIds(), query, favoriteOnly, sort,
        serverProbes, source.whiteListNodeIds() + TurkeyLteGroups.matchingIds(nodes)
    )

    private fun isLteGroup(entry: ServerDirectoryEntry): Boolean =
        ServerCollections.isWhiteListLabel(entry.info.title) ||
            entry.manualWhitelist

    /** Display actual provider/user-marked LTE entries above ordinary nodes. */
    private fun putGroupedServerRows(
        sheet: LinearLayout,
        entries: List<ServerDirectoryEntry>,
        returnHomeAfterSelection: Boolean,
        onFavoriteChanged: (() -> Unit)? = null,
    ) {
        val (lte, ordinary) = entries.partition(::isLteGroup)
        if (lte.isNotEmpty()) {
            add(sheet, t("📶 LTE-доступ · ${lte.size}", 12.5f,
                VainahDesign.green, true).apply {
                setPadding(dp(9), dp(9), dp(9), dp(7))
            })
            putServerRows(sheet, lte, returnHomeAfterSelection, onFavoriteChanged)
        }
        if (ordinary.isNotEmpty()) {
            if (lte.isNotEmpty()) add(sheet, t("Обычные серверы", 12.5f,
                ServerListVisual.mutedColor(), true).apply {
                setPadding(dp(9), dp(14), dp(9), dp(7))
            })
            putServerRows(sheet, ordinary, returnHomeAfterSelection, onFavoriteChanged)
        }
    }

    private fun putServerRows(
        sheet: LinearLayout,
        entries: List<ServerDirectoryEntry>,
        returnHomeAfterSelection: Boolean,
        onFavoriteChanged: (() -> Unit)? = null,
    ) {
        for ((position, entry) in entries.withIndex()) {
            val node = nodes[entry.index]
            val observation = serverProbes.firstOrNull { it.index == entry.index }
            val latency = ServerRowPresentation.latency(observation)
            val server = ServerListVisual.row(
                context = this,
                info = entry.info,
                latency = latency,
                isSelected = node.uri == selected?.uri,
                isFavorite = entry.favorite,
                isWhitelist = isLteGroup(entry),
                isConnectable = SubscriptionNodeSupport.canConnect(node.uri),
                onFavoriteClick = {
                    if (source.setFavorite(node.uri, nodes, !entry.favorite)) {
                        if (onFavoriteChanged != null) onFavoriteChanged() else render()
                    } else {
                        popup("Не удалось сохранить избранное. Максимум " +
                            ServerDirectory.MAX_FAVORITES + " серверов.")
                    }
                },
            ) {
                if (!SubscriptionNodeSupport.canConnect(node.uri)) {
                    popup("Этот транспорт пока недоступен в текущем движке VainahVPN: " +
                        entry.info.subtitle + ". Сервер показан без подключения.")
                    return@row
                }
                // Selecting a row never interrupts an existing VPN tunnel.
                selected = node
                if (returnHomeAfterSelection) {
                    serverListExpanded = true
                    page = Page.HOME
                }
                render()
            }
            sheet.addView(server, LinearLayout.LayoutParams(-1, -2))
            if (position + 1 < entries.size) {
                sheet.addView(ServerListVisual.separator(this),
                    LinearLayout.LayoutParams(-1, dp(1)))
            }
        }
    }

    private fun home(body: LinearLayout) {
        val ink = ServerListVisual.textColor()
        val muted = ServerListVisual.mutedColor()
        val accent = ServerListVisual.accentColor()

        val upper = horizontal()
        val settingsButton = lightAction("⚙").apply {
            contentDescription = "Настройки VainahVPN"
            textSize = 22f
        }
        upper.addView(settingsButton, LinearLayout.LayoutParams(dp(45), dp(45)))
        settingsButton.setOnClickListener { page = Page.SETTINGS; render() }
        val brand = horizontal().apply {
            gravity = Gravity.CENTER
            addView(VainahShieldView(this@MainActivity),
                LinearLayout.LayoutParams(dp(34), dp(34)))
            val title = column()
            add(title, t("VainahVPN", 20f, ink, true))
            add(title, t("Твоё соединение · Твои правила", 10f, muted), 3)
            addView(title, LinearLayout.LayoutParams(-2, -2).apply {
                marginStart = dp(8)
            })
        }
        upper.addView(brand, LinearLayout.LayoutParams(0, -2, 1f))
        val addProfile = lightAction("+").apply {
            contentDescription = "Добавить VPN-подписку"
            textSize = 25f
        }
        upper.addView(addProfile, LinearLayout.LayoutParams(dp(45), dp(45)))
        addProfile.setOnClickListener { page = Page.ACCOUNT; render() }
        add(body, upper, 4)

        val quickStatus = card()
        add(body, quickStatus, 13)
        add(quickStatus, tag("СОСТОЯНИЕ СОЕДИНЕНИЯ"))
        val networkStatus = t("Определяем сеть Android…", 13f, white, true)
        networkStatusView = networkStatus
        add(quickStatus, networkStatus, 7)
        add(quickStatus, t("VPN-движок: " +
            if (EngineRegistry.active.ready) "libbox готов" else
                "недоступен в этой сборке", 11.5f, grey), 6)
        add(quickStatus, VainahUi.infoStrip(this,
            "Статус Android-сети не означает, что внешний IP уже защищён."), 10)

        val hero = column().apply {
            gravity = Gravity.CENTER_HORIZONTAL
            // Original premium lavender ring, matching the approved design.
            setPadding(dp(9), dp(14), dp(9), dp(12))
        }
        add(body, hero, 13)
        val ring = FrameLayout(this).apply {
            background = GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                intArrayOf(
                    VainahDesign.accentDark,
                    VainahDesign.previewTop
                )
            ).apply {
                shape = GradientDrawable.OVAL
                setStroke(dp(1), VainahDesign.softPurple)
            }
            elevation = dp(3).toFloat()
        }
        val power = PowerOrbView(this).apply {
            contentDescription = "Включить или отключить VPN"
            isClickable = true
            isFocusable = true
            val circle = GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                if (VainahTheme.isDark)
                    intArrayOf(VainahDesign.purple, VainahDesign.accentDark)
                else intArrayOf(Color.WHITE, Color.rgb(248, 249, 252))
            ).apply {
                shape = GradientDrawable.OVAL
                setStroke(dp(2), VainahDesign.softPurple)
            }
            background = RippleDrawable(
                ColorStateList.valueOf(Color.argb(65, 194, 128, 255)),
                circle, null
            )
            elevation = dp(5).toFloat()
            setOnClickListener {
                if (VpnConnectionState.read(this@MainActivity).canDisconnect) disconnect()
                else connect()
            }
        }
        powerOrb = power
        ring.addView(power, FrameLayout.LayoutParams(
            dp(172), dp(172), Gravity.CENTER
        ))
        hero.addView(ring, LinearLayout.LayoutParams(dp(223), dp(223)))
        val status = t("Не подключено", 21f, ink, true).apply {
            gravity = Gravity.CENTER
        }
        stateView = status
        add(hero, status, 17)
        val nextNode = selected?.let { ServerRowPresentation.describe(it, 0) }
        val selectedName = if (nextNode == null) "Выбери сервер из списка ниже"
        else nextNode.flag + "  " + nextNode.title
        add(hero, t(selectedName, 14f, ink, true).apply {
            gravity = Gravity.CENTER
            maxLines = 1
            ellipsize = android.text.TextUtils.TruncateAt.END
        }, 8)
        val detail = t(
            "Туннель ещё не проверен. После подключения проверь внешний IP.",
            11.5f, muted
        ).apply { gravity = Gravity.CENTER }
        detailView = detail
        add(hero, detail, 7)
        val connect = action("Подключиться", true).apply {
            setTextColor(Color.WHITE)
            background = RippleDrawable(
                ColorStateList.valueOf(Color.argb(55, 255, 255, 255)),
                GradientDrawable(
                    GradientDrawable.Orientation.LEFT_RIGHT,
                    intArrayOf(VainahDesign.purple, VainahDesign.accentDark)
                ).apply { cornerRadius = dp(16).toFloat() },
                null
            )
        }
        connectView = connect
        add(hero, connect, 16)
        connect.setOnClickListener {
            if (VpnConnectionState.read(this).canDisconnect) disconnect()
            else connect()
        }

        val sheet = ServerListVisual.sheet(this)
        add(body, sheet, 12)
        val heading = horizontal().apply {
            setPadding(dp(10), 0, dp(10), dp(8))
        }
        val title = column()
        title.addView(t("VainahVPN · Серверы", 17.5f, ink, true))
        title.addView(t(
            if (nodes.isEmpty()) "Подписка пока не загружена"
            else "${nodes.size} серверов · твоя подписка",
            11f, muted
        ), LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(4) })
        heading.addView(title, LinearLayout.LayoutParams(0, -2, 1f))
        val refresh = lightAction("⟳").apply {
            contentDescription = "Обновить серверы из подписки"
            textSize = 22f
            isEnabled = !source.busy
        }
        heading.addView(refresh, LinearLayout.LayoutParams(dp(42), dp(42)))
        refresh.setOnClickListener { refreshServers(true) }
        val measure = lightAction("мс").apply {
            textSize = 12f
            contentDescription = "Измерить TCP-задержку всех серверов"
            isEnabled = nodes.any { SubscriptionNodeSupport.canConnect(it.uri) } &&
                !serverProbeRunning &&
                !VpnConnectionState.read(this@MainActivity).canDisconnect
        }
        heading.addView(measure, LinearLayout.LayoutParams(dp(42), dp(42)).apply {
            marginStart = dp(6)
        })
        measure.setOnClickListener { probeServersAndChoose(selectBest = false) }
        val allList = lightAction("⋯").apply {
            textSize = 21f
            contentDescription = "Показать все серверы"
        }
        heading.addView(allList, LinearLayout.LayoutParams(dp(42), dp(42)).apply {
            marginStart = dp(6)
        })
        allList.setOnClickListener {
            serverCollection = ServerCollection.ALL
            page = Page.LOCATIONS
            render()
        }
        add(sheet, heading)
        val infoText = if (source.busy) "Обновляем подписку…"
        else cacheMessage
        add(sheet, t(infoText, 11f, muted).apply {
            setPadding(dp(13), 0, dp(13), dp(11))
        })
        lastError?.let { safeError ->
            add(sheet, t(safeError, 11.5f, Color.rgb(172, 78, 82)).apply {
                setPadding(dp(13), 0, dp(13), dp(12))
            })
        }
        if (nodes.isEmpty()) {
            add(sheet, t(
                "Добавь профиль и обнови серверы. Демонстрационные узлы не показываются.",
                13f, muted
            ).apply { setPadding(dp(13), dp(12), dp(13), dp(15)) })
        } else {
            val ordered = directory()
            val prioritized = ordered.filter(::isLteGroup) +
                ordered.filterNot(::isLteGroup)
            val visible = if (serverListExpanded)
                prioritized.size else minOf(8, prioritized.size)
            putGroupedServerRows(sheet, prioritized.take(visible), false)
            if (nodes.size > 8) {
                val expand = lightAction(if (visible == ordered.size)
                    "Свернуть список" else "Показать все ${nodes.size} серверов")
                add(sheet, expand, 8)
                expand.setOnClickListener {
                    serverListExpanded = visible != nodes.size
                    render()
                }
            }
        }
        val footer = horizontal().apply {
            setPadding(dp(8), dp(10), dp(8), 0)
        }
        val more = lightAction("Все серверы")
        footer.addView(more, LinearLayout.LayoutParams(0, dp(48), 1f))
        more.setOnClickListener {
            serverCollection = ServerCollection.ALL
            page = Page.LOCATIONS
            render()
        }
        val whiteList = lightAction("Белые списки")
        footer.addView(whiteList, LinearLayout.LayoutParams(0, dp(48), 1f).apply {
            marginStart = dp(8)
        })
        whiteList.setOnClickListener {
            serverCollection = ServerCollection.LTE
            page = Page.LOCATIONS
            render()
        }
        add(sheet, footer)
        val smart = action("✦ Умный выбор по TCP-задержке", true)
        smart.isEnabled = nodes.any { SubscriptionNodeSupport.canConnect(it.uri) } &&
            !serverProbeRunning && !VpnConnectionState.read(this).canDisconnect
        smart.contentDescription =
            "Измерить реальные входные TCP-подключения и выбрать быстрый сервер"
        add(body, smart, 12)
        smart.setOnClickListener { probeServersAndChoose(selectBest = true) }
        add(body, t(
            "Замер TCP не равен скорости туннеля. Ручной выбор и текущий " +
                "VPN-сеанс не заменяются автоматически.",
            11f, muted
        ), 9)

        val trafficPanel = card()
        add(body, trafficPanel, 15)
        add(trafficPanel, tag("МОНИТОРИНГ"))
        add(trafficPanel, t("Скорость прямо сейчас", 18f, white, true), 7)
        val traffic = t("Статистика появится после подключения.", 12f, muted)
        trafficView = traffic
        add(trafficPanel, traffic, 7)
        val sparkline = TrafficSparklineView(this)
        trafficChart = sparkline
        trafficPanel.addView(sparkline, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, dp(132)).apply {
                topMargin = dp(9)
            })
        sparkline.show(trafficTimeline.snapshot())
        add(trafficPanel, VainahUi.infoStrip(this,
            "График строится только по свежим счётчикам libbox. " +
                "Пинг сервера и проверка внешнего IP — отдельные тесты."), 9)
    }

    private fun account(body: LinearLayout) {
        val live = card()
        add(body, live, 16)
        add(live, tag("МОЯ ПОДПИСКА"))
        add(live, t("Подписка VainahVPN", 20f, white, true), 9)
        add(live, t(
            "Кабинет и актуальные тарифы доступны прямо в приложении. " +
                "На сайт переходит только оформление выбранного тарифа.",
            12f, grey
        ), 10)
        add(live, VainahUi.detailRow(this, "VPN-профиль",
            if (source.savedLink() == null) "Не добавлен" else "Сохранён",
            if (source.savedLink() == null) VainahUi.Tone.NEUTRAL
            else VainahUi.Tone.SUCCESS), 12)
        add(live, VainahUi.detailRow(this, "Серверов из подписки",
            nodes.size.toString(), VainahUi.Tone.PURPLE), 7)
        add(live, VainahUi.infoStrip(this,
            "Тариф, оплаченные заказы и срок подписки доступны после " +
                "входа в официальный кабинет. Данные не подменяются локальными."), 11)
        val onlineAccount = action("Личный кабинет в приложении", true)
        add(live, onlineAccount, 12)
        onlineAccount.setOnClickListener { openOfficialPage("account.html") }
        val cabinetShortcuts = horizontal()
        val onlinePlans = action("Тарифы")
        cabinetShortcuts.addView(onlinePlans,
            LinearLayout.LayoutParams(0, dp(46), 1f))
        onlinePlans.setOnClickListener { openOfficialPage("plans.html") }
        val onlineDevices = action("Устройства")
        cabinetShortcuts.addView(onlineDevices,
            LinearLayout.LayoutParams(0, dp(46), 1f).apply {
                marginStart = dp(8)
            })
        onlineDevices.setOnClickListener { openOfficialPage("my-devices.html") }
        add(live, cabinetShortcuts, 10)

        val profile = card()
        add(body, profile, 14)
        add(profile, tag("VPN-профиль"))
        add(profile, t(if (source.savedLink() == null)
            "Подписка не добавлена" else "Профиль сохранён", 19f, white, true), 9)
        add(profile, t(source.sourceLabel(), 12f, grey), 8)
        add(profile, VainahUi.infoStrip(this,
            "VPN-ключи хранятся в защищённом Android Keystore."), 9)
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
            serverSearchQuery = ""
            showFavoriteServers = false
            serverSort = ServerSort.SUBSCRIPTION
            serverListExpanded = false
            invalidateServerProbes()
            nodes = source.cachedNodes()
            selected = nodes.firstOrNull { SubscriptionNodeSupport.canConnect(it.uri) }
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
            "Войди в свой существующий аккаунт VainahVPN по email, " +
                "Google или Telegram. Заказы и обращения останутся привязаны " +
                "к тому же аккаунту. Платёжные данные приложение не хранит.",
            12f, grey), 8)
        val login = action("Войти по email в приложении", true)
        add(identity, login, 10)
        login.setOnClickListener { openOfficialPage("account.html") }
        if (BuildConfig.VAINAH_CLERK_ENABLED) {
            val nativeClerk = action("Нативный Clerk (тестовый вход)")
            add(identity, nativeClerk, 9)
            nativeClerk.setOnClickListener {
                runCatching {
                    startActivity(Intent().setClassName(this,
                        "app.vainah.vpn.ClerkLoginActivity"))
                }.onFailure { popup("Не удалось открыть окно Clerk.") }
            }
        }
    }

    private fun help(body: LinearLayout) {
        val snapshot = VpnConnectionState.read(this)
        val active = snapshot.canDisconnect && VainahVpnService.runningInProcess
        val status = DiagnosticPresentation.subscription(
            source.savedLink() != null, nodes.size, source.busy, lastError
        )

        val subscription = card()
        add(body, subscription, 13)
        add(subscription, tag("СЕРВЕР ПОДПИСКИ"))
        add(subscription, t(status.headline, 17f, white, true), 8)
        add(subscription, t(status.explanation, 12f,
            if (status.warning) errorColor else grey), 8)
        add(subscription, VainahUi.infoStrip(this,
            status.secondary + " · " + source.sourceLabel()), 12)

        val engine = card()
        add(body, engine, 12)
        add(engine, VainahUi.detailRow(this, "VPN-движок libbox",
            if (EngineRegistry.active.ready) "✓ Установлен" else "Недоступен",
            if (EngineRegistry.active.ready) VainahUi.Tone.SUCCESS
            else VainahUi.Tone.WARNING))

        val network = VpnUnderlayStatus.read(this)
        val networkName = when (network.transport) {
            "wifi" -> "Wi-Fi"
            "cellular" -> "4G / 5G"
            "ethernet" -> "Ethernet"
            "other" -> "Другая сеть"
            else -> "Нет сети"
        }
        val physical = card()
        add(body, physical, 12)
        add(physical, tag("ФИЗИЧЕСКАЯ СЕТЬ"))
        add(physical, t("Состояние во время VPN-сеанса",
            17f, white, true), 8)
        add(physical, VainahUi.detailRow(this,
            if (active) "Физический интерфейс" else "Последний интерфейс",
            networkName, VainahUi.Tone.PURPLE), 12)
        add(physical, VainahUi.detailRow(this, "Проверка Android",
            if (network.validated) "Подтверждена" else "Не подтверждена",
            if (network.validated) VainahUi.Tone.SUCCESS
            else VainahUi.Tone.NEUTRAL), 5)
        add(physical, VainahUi.detailRow(this,
            "Переходов между сетями", network.transitions.toString()), 5)
        add(physical, t(
            "Это состояние физической сети Android, а не доказательство " +
                "работы VPN или отсутствия DNS-утечек.",
            11.5f, grey), 10)
        val tools = horizontal()
        val report = action("Скопировать отчёт", true).apply {
            textSize = 12f
            contentDescription = "Скопировать обезличенный диагностический отчёт"
        }
        tools.addView(report, LinearLayout.LayoutParams(0, dp(49), 1f))
        val retry = action("Обновить серверы").apply {
            textSize = 12f
            contentDescription = "Обновить список серверов из HTTPS-подписки"
            isEnabled = !source.busy
        }
        tools.addView(retry, LinearLayout.LayoutParams(0, dp(49), 1f).apply {
            marginStart = dp(8)
        })
        add(physical, tools, 13)
        report.setOnClickListener {
            val diag = getSharedPreferences("vpn_diagnostics", MODE_PRIVATE)
            val current = VpnConnectionState.read(this)
            val underlay = VpnUnderlayStatus.read(this)
            val safeReport = VpnDiagnosticReport.create(
                current.phase,
                diag.getString("last_stage", null),
                diag.getString("vpn_probe_reason", null),
                Build.VERSION.SDK_INT,
                VainahVpnService.runningInProcess,
                networkFacts = currentRouteFacts(),
                underlay = VpnUnderlayFacts(
                    transport = underlay.transport,
                    validated = underlay.validated,
                    transitions = underlay.transitions
                ),
                handoffEvents = VpnUnderlayStatus.history(this),
                recoveryCode = VpnUnderlayStatus.recovery(
                    this, current.canDisconnect && VainahVpnService.runningInProcess
                ).code,
                failureCode = if (current.phase == VpnConnectionState.FAILED)
                    diag.getString("last_failure_code", null) else null
            )
            val clipboard = getSystemService(CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText(
                "VainahVPN diagnostic", safeReport
            ))
            popup("Безопасный отчёт скопирован. Ключи, адреса серверов и ссылки не включены.")
        }
        retry.setOnClickListener { refreshServers(true) }

        val recovery = VpnUnderlayStatus.recovery(this, active)
        val recoveryCard = card()
        add(body, recoveryCard, 12)
        add(recoveryCard, tag("ВОССТАНОВЛЕНИЕ СЕТИ"))
        add(recoveryCard, t(
            DiagnosticPresentation.tunnelHeadline(
                snapshot.phase, VainahVpnService.runningInProcess
            ), 17f, white, true), 8)
        add(recoveryCard, t(recovery.message, 12f,
            if (recovery.attention) errorColor else grey), 9)
        add(recoveryCard, VainahUi.infoStrip(this,
            if (active) "При неожиданной остановке движка доступны до двух " +
                "попыток восстановления. При ручном отключении они отменяются."
            else "Для проверки VPN запусти туннель на главной странице."), 10)
        val openHome = action("Управление подключением")
        add(recoveryCard, openHome, 11)
        openHome.setOnClickListener { page = Page.HOME; render() }

        val failureCode = getSharedPreferences("vpn_diagnostics", MODE_PRIVATE)
            .getString("last_failure_code", null)
        if (snapshot.phase == VpnConnectionState.FAILED && failureCode != null) {
            val advice = VpnFailureAdvisor.fromCode(failureCode)
            val failure = card()
            add(body, failure, 12)
            add(failure, tag("ПОСЛЕДНЯЯ ОШИБКА LIBBOX"))
            add(failure, t(advice.title, 16f, white, true), 8)
            add(failure, t(advice.action, 12f, grey), 8)
            add(failure, t("Код: " +
                VpnFailureAdvisor.sanitizedCode(failureCode), 11f, teal), 7)
        }

        val expanded = action(if (showAdvancedDiagnostics)
            "Скрыть дополнительные проверки" else "Дополнительные проверки и история")
        add(body, expanded, 13)
        expanded.setOnClickListener {
            showAdvancedDiagnostics = !showAdvancedDiagnostics
            render()
        }
        if (!showAdvancedDiagnostics) return

        val routes = card()
        add(body, routes, 12)
        add(routes, tag("DNS / IPv4 / IPv6"))
        add(routes, t("Маршруты Android VPN", 17f, white, true), 8)
        val facts = currentRouteFacts()
        val assessment = VpnRouteAdvisor.assess(active, facts)
        add(routes, t(if (routeScanRunning)
            "Проверяем Android…" else assessment.title,
            14f, white, true), 9)
        add(routes, t(assessment.explanation, 12f,
            if (assessment.needsReview) errorColor else grey), 8)
        if (facts != null) {
            fun flag(value: Boolean?): String = when (value) {
                true -> "есть"
                false -> "нет"
                else -> "неизвестно"
            }
            add(routes, VainahUi.detailRow(this, "VPN-сеть", flag(facts.visible)), 10)
            add(routes, VainahUi.detailRow(this,
                "IPv4", flag(facts.ipv4DefaultRoute)), 5)
            add(routes, VainahUi.detailRow(this,
                "IPv6", flag(facts.ipv6DefaultRoute)), 5)
            add(routes, VainahUi.detailRow(this,
                "DNS", flag(facts.dnsConfigured)), 5)
        }
        val inspect = action(if (routeScanRunning) "Проверяем…" else
            "Проверить маршруты и DNS")
        inspect.isEnabled = !routeScanRunning && active
        add(routes, inspect, 11)
        inspect.setOnClickListener { inspectVpnRoutes() }
        add(routes, t("Проверка локальная: не измеряет DNS-утечки, " +
            "внешний IP или успешную передачу VPN-трафика.", 11f, grey), 8)

        val history = card()
        add(body, history, 12)
        add(history, tag("ИСТОРИЯ СЕТИ"))
        val events = VpnUnderlayStatus.history(this)
        add(history, t(if (events.isEmpty())
            "Переходы пока не зафиксированы"
            else "Последние ${minOf(events.size, 6)} переходов",
            16f, white, true), 8)
        fun label(name: String): String = when (name) {
            "wifi" -> "Wi-Fi"
            "cellular" -> "4G/5G"
            "ethernet" -> "Ethernet"
            "none" -> "Нет сети"
            else -> "Другая сеть"
        }
        for (event in events.takeLast(6).asReversed()) {
            add(history, VainahUi.detailRow(this,
                label(event.from) + " → " + label(event.to),
                if (event.validated) "Подтверждено" else "Не проверено",
                if (event.validated) VainahUi.Tone.SUCCESS
                else VainahUi.Tone.NEUTRAL), 6)
        }
        add(history, t(
            "История не подтверждает, что сайты открывались через VPN.",
            11f, grey), 11)
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
        val ink = ServerListVisual.textColor()
        val muted = ServerListVisual.mutedColor()
        val summary = card()
        add(body, summary, 13)
        val header = horizontal().apply {
            setPadding(dp(2), dp(2), dp(2), dp(8))
        }
        val text = column()
        add(text, tag("ВСЕ СЕРВЕРЫ"))
        add(text, t(
            if (nodes.isEmpty()) "Список пока пуст"
            else "${nodes.size} серверов из подписки",
            18f, ink, true
        ), 6)
        add(text, t("Сохранено конфигураций: ${nodes.size}",
            11f, muted), 5)
        header.addView(text, LinearLayout.LayoutParams(0, -2, 1f))
        val refresh = lightAction("⟳").apply {
            contentDescription = "Обновить список серверов"
            textSize = 22f
            isEnabled = !source.busy
        }
        header.addView(refresh, LinearLayout.LayoutParams(dp(48), dp(48)))
        refresh.setOnClickListener { refreshServers(true) }
        add(summary, header)
        add(summary, VainahUi.infoStrip(this,
            if (source.busy) "Загружаем серверы из подписки…"
            else cacheMessage), 8)
        lastError?.let { problem ->
            add(summary, t(problem, 11.5f, errorColor), 8)
        }
        val sheet = ServerListVisual.sheet(this)
        add(body, sheet, 12)
        // Search/filter only updates the row container. Keeping EditText
        // alive preserves keyboard focus while the user is typing.
        val search = EditText(this).apply {
            hint = "Поиск по стране или названию"
            setSingleLine(true)
            inputType = InputType.TYPE_CLASS_TEXT
            textSize = 14f
            setTextColor(ink)
            setHintTextColor(muted)
            setPadding(dp(12), dp(9), dp(12), dp(9))
            background = shape(VainahDesign.surface, VainahDesign.border, 13)
            setText(serverSearchQuery)
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO
        }
        add(sheet, search, 8)
        val categoryButtons = mutableListOf<Pair<ServerCollection, Button>>()
        val categoryRow = horizontal().apply {
            setPadding(dp(8), dp(5), dp(8), dp(5))
        }
        for (category in listOf(
            ServerCollection.ALL, ServerCollection.LTE,
            ServerCollection.GAMES, ServerCollection.STREAMING,
            ServerCollection.FAST, ServerCollection.RECOMMENDED
        )) {
            val chip = lightAction(category.title).apply {
                textSize = 10f
                minHeight = dp(36)
                setMinWidth(0)
                setMinimumWidth(0)
                setPadding(dp(12), 0, dp(12), 0)
                contentDescription = "Категория серверов: " + category.title
            }
            categoryRow.addView(chip, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, dp(36)
            ).apply { marginEnd = dp(6) })
            categoryButtons.add(category to chip)
        }
        val categoryScroll = HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            isFillViewport = false
            addView(categoryRow)
        }
        add(sheet, categoryScroll, 8)
        val whiteInfo = VainahUi.infoStrip(this,
            "Список H1Cloud обновляется автоматически по расписанию Android. " +
                "LTE-метка не подтверждает работу конкретного сервера.")
        add(sheet, whiteInfo, 7)
        val lteControls = horizontal()
        val viewLte = action("LTE-серверы", true).apply {
            textSize = 11.5f
            contentDescription = "Показать категорию LTE-серверов"
        }
        lteControls.addView(viewLte, LinearLayout.LayoutParams(
            0, dp(45), 1f))
        viewLte.setOnClickListener {
            serverCollection = ServerCollection.WHITELIST
            render()
        }
        val editWhite = lightAction("Отметить мои LTE").apply {
            textSize = 11f
            contentDescription = "Выбрать реальные серверы с LTE-доступом"
        }
        lteControls.addView(editWhite, LinearLayout.LayoutParams(
            0, dp(45), 1f
        ).apply { marginStart = dp(8) })
        add(sheet, lteControls, 9)
        editWhite.setOnClickListener { chooseWhiteListNodes() }
        val controls = horizontal().apply {
            setPadding(dp(5), dp(9), dp(5), dp(12))
        }
        val favoriteButton = lightAction("☆ Избранные").apply {
            textSize = 12f
        }
        controls.addView(favoriteButton, LinearLayout.LayoutParams(
            0, dp(40), 1f
        ))
        val sortButton = lightAction("Сортировка").apply {
            textSize = 12f
        }
        controls.addView(sortButton, LinearLayout.LayoutParams(
            0, dp(40), 1f
        ).apply { marginStart = dp(7) })
        add(sheet, controls)

        val count = t("", 11.5f, muted).apply {
            setPadding(dp(13), dp(5), dp(13), dp(10))
        }
        add(sheet, count)
        val results = column()
        add(sheet, results)

        val redrawRows = object : () -> Unit {
            override fun invoke() {
                val matches = ServerCollections.filter(
                    directory(serverSearchQuery, false, serverSort),
                    serverCollection
                )
                val whiteMode = serverCollection == ServerCollection.WHITELIST
                whiteInfo.text = if (whiteMode)
                    "LTE-группа включает только узлы с меткой в подписке " +
                        "или отмеченные вручную. Пометка не включает LTE-доступ."
                else "Новые конфигурации H1Cloud обновляются по расписанию Android. " +
                    "В списке только реальные узлы подписки."
                favoriteButton.text = if (serverCollection == ServerCollection.FAVORITES)
                    "★ Только избранные" else "☆ Избранные"
                for ((category, button) in categoryButtons) {
                    val active = category == serverCollection
                    button.background = VainahUi.buttonBackground(
                        this@MainActivity, active
                    )
                    button.setTextColor(if (active) Color.WHITE else white)
                    button.isSelected = active
                }
                sortButton.text = when (serverSort) {
                    ServerSort.SUBSCRIPTION -> "По подписке"
                    ServerSort.COUNTRY -> "По стране"
                    ServerSort.MEASURED_TCP -> "По TCP"
                }
                val measured = serverProbes.count {
                    it.attempts == ServerTcpSelector.ATTEMPTS_PER_NODE &&
                        it.successes >= 2
                }
                val connectable = nodes.count {
                    SubscriptionNodeSupport.canConnect(it.uri)
                }
                count.text = if (whiteMode)
                    "LTE-группа: ${matches.size} из ${nodes.size}"
                else "${matches.size} из ${nodes.size} · подключаемых ${connectable} · TCP ${measured}"
                results.removeAllViews()
                if (matches.isEmpty()) {
                    val message = if (serverSearchQuery.isNotBlank())
                        "Нет совпадений по запросу в этой категории. Очисти поиск."
                    else ServerCollections.emptyMessage(serverCollection, nodes.isNotEmpty())
                    add(results, t(message, 13f, muted).apply {
                        setPadding(dp(13), dp(12), dp(13), dp(18))
                    })
                } else {
                    putGroupedServerRows(results, matches, true, onFavoriteChanged = {
                        invoke()
                    })
                }
            }
        }
        favoriteButton.setOnClickListener {
            serverCollection = if (serverCollection == ServerCollection.FAVORITES)
                ServerCollection.ALL else ServerCollection.FAVORITES
            redrawRows()
        }
        for ((category, button) in categoryButtons) {
            button.setOnClickListener {
                serverCollection = category
                redrawRows()
            }
        }
        sortButton.setOnClickListener {
            val options = arrayOf("По порядку подписки", "По стране",
                "По измеренной TCP-задержке")
            AlertDialog.Builder(this).setTitle("Сортировка серверов")
                .setSingleChoiceItems(options, serverSort.ordinal) { dialog, which ->
                    serverSort = ServerSort.values()[which]
                    dialog.dismiss()
                    redrawRows()
                }.setNegativeButton("Отмена", null).show()
        }
        search.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int,
                count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int,
                before: Int, count: Int) {
                serverSearchQuery = s?.toString()?.take(60).orEmpty()
                redrawRows()
            }
            override fun afterTextChanged(s: Editable?) = Unit
        })
        redrawRows()
        val actions = horizontal().apply {
            setPadding(dp(8), dp(12), dp(8), 0)
        }
        val addProfile = lightAction("+ Подписка")
        actions.addView(addProfile, LinearLayout.LayoutParams(0, dp(48), 1f))
        addProfile.setOnClickListener { page = Page.ACCOUNT; render() }
        add(sheet, actions)

        val measurement = column().apply {
            background = shape(ServerListVisual.cardColor(), VainahDesign.border, 21)
            setPadding(dp(17), dp(18), dp(17), dp(20))
        }
        add(body, measurement, 16)
        add(measurement, tag("ИЗМЕРЕНИЕ СЕРВЕРОВ"))
        add(measurement, t("TCP-задержка", 17f, ink, true), 7)
        add(measurement, t(serverProbeMessage, 12f, muted), 7)
        add(measurement, t(
            "Проверяем входные серверы без VPN. TCP-задержка — " +
                "время соединения, не пинг внутри туннеля.",
            12f, muted
        ), 9)
        val probe = action(
            if (serverProbeRunning) "Проверяем серверы…"
            else "Повторить замер и выбрать быстрый", true
        )
        probe.isEnabled = nodes.any { SubscriptionNodeSupport.canConnect(it.uri) } &&
            !serverProbeRunning && !VpnConnectionState.read(this).canDisconnect
        add(measurement, probe, 12)
        probe.setOnClickListener { probeServersAndChoose() }
    }

    private fun chooseWhiteListNodes() {
        if (nodes.isEmpty()) {
            popup("Сначала добавь подписку и обнови серверы.")
            return
        }
        val visible = ServerRowPresentation.describeList(nodes)
        val current = source.whiteListNodeIds() + TurkeyLteGroups.matchingIds(nodes)
        val checked = BooleanArray(nodes.size) { index ->
            ServerDirectory.identity(nodes[index].uri) in current
        }
        val options = visible.map { it.flag + "  " + it.title }.toTypedArray()
        AlertDialog.Builder(this)
            .setTitle("LTE-доступ · серверы H1Cloud")
            // Android cannot reliably show setMessage and multi-choice rows
            // together in the same AlertDialog. Explanation is on the page.
            .setMultiChoiceItems(options, checked) { _, index, value ->
                checked[index] = value
            }
            .setPositiveButton("Сохранить") { _, _ ->
                val selectedUris = nodes.indices.filter { checked[it] }
                    .map { nodes[it].uri }.toSet()
                if (source.setWhiteListNodes(nodes, selectedUris)) {
                    serverCollection = ServerCollection.WHITELIST
                    render()
                } else {
                    popup("Не удалось сохранить группу. Проверь VPN-подписку.")
                }
            }
            .setNegativeButton("Отмена", null)
            .show()
    }

    private fun invalidateServerProbes() {
        serverProbeGeneration++
        serverProbeRunning = false
        serverProbeAttempted = false
        activeProbePool?.shutdownNow()
        activeProbePool = null
        serverProbes = emptyList()
        serverProbeMessage = "TCP-задержка входных узлов ещё не измерялась."
    }

    private fun probeServersAndChoose(selectBest: Boolean = true) {
        if (serverProbeRunning) return
        if (VpnConnectionState.read(this).canDisconnect) {
            popup("Для корректной проверки сначала отключи VPN.")
            return
        }
        val capture = nodes.mapIndexedNotNull { index, node ->
            if (SubscriptionNodeSupport.canConnect(node.uri)) index to node
            else null
        }.take(ServerTcpSelector.MAX_PROBED_NODES)
        if (capture.isEmpty()) {
            popup("В подписке нет узлов, поддерживаемых этим движком для TCP-замеров.")
            return
        }
        serverProbeRunning = true
        serverProbeAttempted = true
        val version = ++serverProbeGeneration
        val selectedBefore = selected?.uri
        val pool = Executors.newFixedThreadPool(minOf(4, capture.size))
        activeProbePool = pool
        serverProbeMessage = "Проверяем TCP-подключение к ${capture.size} серверам…"
        render()
        Thread({
            val measured = try {
                val futures = capture.map { (index, node) ->
                    index to pool.submit(Callable {
                        ServerTcpMeasurement.sample(node).copy(index = index)
                    })
                }
                // Bound the complete server scan, even when an OS DNS lookup
                // or socket operation does not honour a connect timeout.
                // No timed-out node may receive an invented latency.
                val deadline = System.nanoTime() +
                    java.util.concurrent.TimeUnit.SECONDS.toNanos(90)
                futures.map { (index, future) ->
                    try {
                        val remaining = deadline - System.nanoTime()
                        if (remaining <= 0L) throw java.util.concurrent.TimeoutException()
                        future.get(remaining, java.util.concurrent.TimeUnit.NANOSECONDS)
                    } catch (_: Exception) {
                        future.cancel(true)
                        ServerTcpObservation(index,
                            ServerTcpSelector.ATTEMPTS_PER_NODE, emptyList())
                    }
                }
            } finally {
                pool.shutdownNow()
            }
            main.post {
                if (version != serverProbeGeneration || isFinishing || isDestroyed)
                    return@post
                serverProbeRunning = false
                activeProbePool = null
                val unchanged = capture == nodes.mapIndexedNotNull { index, node ->
                    if (SubscriptionNodeSupport.canConnect(node.uri)) index to node
                    else null
                }.take(ServerTcpSelector.MAX_PROBED_NODES) &&
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
                    val available = measured.count { it.successes >= 2 }
                    if (best == null) {
                        serverProbeMessage =
                            "TCP: нет надёжных замеров. Проверь сеть или настройки узлов."
                    } else {
                        val chosen = nodes[best]
                        val latency = measured.firstOrNull { it.index == best }?.medianMs
                        val summary = "TCP: ${available} из ${capture.size} · лучший ${latency} мс."
                        if (selectBest && selected?.uri == selectedBefore) {
                            selected = nodes.firstOrNull { it.uri == chosen.uri } ?: selected
                            serverProbeMessage = summary + " Выбран " + chosen.label + "."
                        } else {
                            serverProbeMessage = summary +
                                if (selectBest) " Ручной выбор сохранён."
                                else " Сервер не переключён."
                        }
                    }
                }
                render()
            }
        }, "vainah-tcp-entry-probe").start()
    }

    private fun devices(body: LinearLayout) {
        val deviceCard = card()
        add(body, deviceCard, 12)
        add(deviceCard, tag("Устройства"))
        add(deviceCard, t("Этот Android", 19f, white, true), 9)
        add(deviceCard, t("Android " + Build.VERSION.RELEASE +
            " · " + android.os.Build.MANUFACTURER, 12f, grey), 10)
        add(deviceCard, t("Лимиты и другие устройства смотри в личном кабинете.",
            12f, grey), 10)
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
        val snapshot = VpnConnectionState.read(this)
        val running = snapshot.canDisconnect && VainahVpnService.runningInProcess
        val excluded = SplitTunnelPreferences.read(this)
        val protection = card()
        add(body, protection, 13)
        add(protection, tag("ЦЕНТР БЕЗОПАСНОСТИ"))
        add(protection, t("Защита соединения", 20f, white, true), 8)
        add(protection, t(
            "Реальные статусы устройства — без имитации проверки внешнего IP.",
            12f, grey
        ), 8)
        add(protection, VainahUi.detailRow(this,
            "VPN-туннель",
            if (running) "Создан" else "Не запущен",
            if (running) VainahUi.Tone.SUCCESS else VainahUi.Tone.NEUTRAL), 11)
        add(protection, VainahUi.detailRow(this,
            "VPN-ключи",
            if (source.savedLink() == null) "Не добавлены" else "Keystore",
            if (source.savedLink() == null) VainahUi.Tone.NEUTRAL
            else VainahUi.Tone.SUCCESS), 6)
        add(protection, VainahUi.detailRow(this,
            "HTTPS-подписка",
            if (source.savedLink()?.startsWith("https://") == true)
                "TLS" else "Не используется",
            if (source.savedLink()?.startsWith("https://") == true)
                VainahUi.Tone.SUCCESS else VainahUi.Tone.NEUTRAL), 6)
        add(protection, VainahUi.detailRow(this,
            "Внешний IP и DNS-утечки", "Не проверены"), 6)
        val diagnostics = action("Открыть диагностику", true)
        add(protection, diagnostics, 12)
        diagnostics.setOnClickListener {
            page = Page.DIAGNOSTICS
            render()
        }

        val kill = card()
        add(body, kill, 13)
        add(kill, tag("KILL SWITCH · ANDROID"))
        add(kill, t("Блокировать интернет без VPN", 18f, white, true), 8)
        add(kill, VainahUi.infoStrip(this,
            "Защита от соединения без VPN управляется Android. " +
                "Наличие работающего туннеля не подтверждает включённый Kill Switch."), 9)
        add(kill, t(
            "Настройки VPN → VainahVPN → «Всегда включён VPN» → " +
                "«Блокировать подключения без VPN».",
            12f, grey
        ), 9)
        val openSettings = action("Открыть настройки Android")
        add(kill, openSettings, 12)
        openSettings.setOnClickListener {
            try {
                startActivity(Intent(Settings.ACTION_VPN_SETTINGS))
            } catch (_: android.content.ActivityNotFoundException) {
                startActivity(Intent(Settings.ACTION_SETTINGS))
            }
        }

        val split = card()
        add(body, split, 13)
        add(split, tag("ИСКЛЮЧЕНИЯ ПРИЛОЖЕНИЙ"))
        add(split, t("Какие приложения не используют VPN", 18f,
            white, true), 8)
        add(split, VainahUi.detailRow(this,
            "Исключено приложений", excluded.size.toString(),
            if (excluded.isEmpty()) VainahUi.Tone.SUCCESS
            else VainahUi.Tone.WARNING), 10)
        add(split, t(
            "Исключённые приложения используют обычный интернет. " +
                "Изменения применятся при следующем подключении. " +
                "При системной блокировке обхода такие исключения не работают.",
            11.5f, grey
        ), 8)
        val manageSplit = action("Выбрать исключённые приложения")
        manageSplit.isEnabled = BuildConfig.VAINAH_LIBBOX_ENABLED
        add(split, manageSplit, 11)
        manageSplit.setOnClickListener { editSplitTunnelApps() }

        val lte = card()
        add(body, lte, 13)
        add(lte, tag("LTE · ГРУППЫ СЕРВЕРОВ"))
        add(lte, t("Белые списки H1Cloud", 18f, white, true), 8)
        val matching = directory().count(::isLteGroup)
        add(lte, VainahUi.detailRow(this,
            "В группе LTE", matching.toString() + " из " + nodes.size,
            if (matching > 0) VainahUi.Tone.PURPLE else VainahUi.Tone.NEUTRAL), 9)
        add(lte, VainahUi.infoStrip(this,
            "Турция · 1 и Турция · IP попадают в группу автоматически, " +
                "если они существуют в твоей подписке. Это группировка, " +
                "а не подтверждение LTE-доступа на стороне H1Cloud."), 10)
        val whitelistServers = action("Посмотреть LTE-серверы", true)
        add(lte, whitelistServers, 11)
        whitelistServers.setOnClickListener {
            serverCollection = ServerCollection.WHITELIST
            page = Page.LOCATIONS
            render()
        }

        val accountSecurity = card()
        add(body, accountSecurity, 13)
        add(accountSecurity, tag("БЕЗОПАСНОСТЬ АККАУНТА"))
        add(accountSecurity, t("Мой личный кабинет", 18f, white, true), 8)
        add(accountSecurity, t(
            "Кабинет, устройства и поддержка доступны прямо в VainahVPN. " +
                "VPN-ключи не передаются при входе.",
            12f, grey
        ), 9)
        val account = action("Открыть кабинет в приложении")
        add(accountSecurity, account, 11)
        account.setOnClickListener { openNativeCabinet() }

        val history = card()
        add(body, history, 13)
        add(history, tag("ИСТОРИЯ VPN"))
        add(history, t("Подключения на этом устройстве", 18f, white, true), 7)
        add(history, t("Сохраняются только время и состояние подключения. " +
            "Адреса серверов, ключи и посещённые сайты не записываются.",
            11.5f, grey), 8)
        val events = VpnSessionJournal.read(this)
        if (events.isEmpty()) {
            add(history, t("Истории пока нет.", 12f, grey), 10)
        } else {
            for (event in events.take(8)) {
                add(history, VainahUi.detailRow(this,
                    VpnSessionJournal.title(event.phase),
                    VpnSessionJournal.localTime(event.timestamp),
                    if (event.phase == VpnConnectionState.FAILED)
                        VainahUi.Tone.WARNING else VainahUi.Tone.NEUTRAL), 8)
            }
            val clearHistory = action("Очистить историю устройства")
            add(history, clearHistory, 12)
            clearHistory.setOnClickListener {
                AlertDialog.Builder(this)
                    .setTitle("Очистить историю VPN?")
                    .setMessage("Удалятся только локальные отметки о " +
                        "подключениях. Сама подписка и VPN не изменятся.")
                    .setNegativeButton("Отмена", null)
                    .setPositiveButton("Очистить") { _, _ ->
                        VpnSessionJournal.clear(this)
                        render()
                    }.show()
            }
        }
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
                "не через VainahVPN. Не совмещай с режимом блокировки без VPN.")
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
        add(body, preferences, 12)
        add(preferences, tag("Настройки подключения"))
        add(preferences, t("Параметры VainahVPN", 19f, white, true), 8)
        add(preferences, t(
            "При переходе между Wi-Fi и мобильной сетью приложение обновляет " +
                "сетевой интерфейс. Kill Switch настраивается в Android.",
            12f, grey), 9)
        add(preferences, menuRow("Управление подпиской", "Профиль, продление и тарифы") {
            page = Page.ACCOUNT
            render()
        }, 11)
        add(preferences, ServerListVisual.separator(this), 3)
        add(preferences, menuRow("Диагностика соединения", "DNS, HTTPS и VPN-туннель") {
            page = Page.DIAGNOSTICS
            render()
        }, 3)
        add(preferences, ServerListVisual.separator(this), 3)
        add(preferences, menuRow("Безопасность", "Kill Switch и приложения вне VPN") {
            page = Page.SECURITY
            render()
        }, 3)

        val appearance = card()
        add(body, appearance, 15)
        add(appearance, tag("ВНЕШНИЙ ВИД"))
        add(appearance, t("Оформление VainahVPN", 18f, white, true), 8)
        add(appearance, t(
            "Тёмная фиолетовая тема вдохновлена макетом VainahVPN 3.0. " +
                "Светлая и системная темы также доступны.",
            12f, grey), 8)
        val themeOptions = horizontal()
        for (option in VainahTheme.Mode.values()) {
            val selectedMode = option == VainahTheme.mode
            val button = action(VainahTheme.label(option), selectedMode).apply {
                textSize = 11f
                setPadding(dp(4), 0, dp(4), 0)
                contentDescription = "Тема: " + VainahTheme.label(option)
            }
            themeOptions.addView(button, LinearLayout.LayoutParams(
                0, dp(47), 1f).apply { marginStart = dp(3) })
            button.setOnClickListener {
                if (VainahTheme.mode != option) {
                    VainahTheme.select(this, option)
                    recreate()
                }
            }
        }
        add(appearance, themeOptions, 13)

        val version = card()
        add(body, version, 15)
        add(version, tag("О приложении"))
        add(version, t("VainahVPN " + BuildConfig.VERSION_NAME,
            16f, white, true), 9)
        add(version, t("Тестовая сборка с реальным Android VpnService при наличии libbox. " +
            "Покупки открываются в официальном браузере, без передачи карты приложению.",
            12f, grey), 10)
    }

    private fun more(body: LinearLayout) {
        val profile = card()
        add(body, profile, 13)
        add(profile, tag("ЛИЧНЫЙ КАБИНЕТ"))
        add(profile, t("Мой VainahVPN", 22f, white, true), 8)
        add(profile, t(
            "Подписка, заказы, устройства и поддержка — в одном месте.",
            12f, grey
        ), 8)
        val link = source.savedLink()
        add(profile, VainahUi.detailRow(this,
            "VPN-профиль на устройстве",
            if (link == null) "Не добавлен" else "Сохранён",
            if (link == null) VainahUi.Tone.NEUTRAL
            else VainahUi.Tone.SUCCESS), 9)
        add(profile, VainahUi.detailRow(this,
            "Загружено серверов",
            nodes.size.toString(), VainahUi.Tone.PURPLE), 6)
        add(profile, VainahUi.infoStrip(this,
            "Войди по коду из письма, проверь подписку и заказы " +
                "в Android. VPN-профиль независим от входа в аккаунт."), 11)
        val enter = action("Открыть мой кабинет", true)
        add(profile, enter, 12)
        enter.setOnClickListener { openOfficialPage("account.html") }

        val services = card()
        add(body, services, 13)
        add(services, tag("МОИ СЕРВИСЫ"))
        add(services, t("Управление аккаунтом", 18f, white, true), 7)
        for ((title, target) in CabinetNavigation.sections()) {
            val description = when (target) {
                "account.html" -> "Мой профиль, подписка и история заказов"
                "plans.html" -> "Продление и доступные варианты"
                "my-devices.html" -> "Мои устройства и лимиты"
                "support-center.html" -> "Мои обращения и ответы оператора"
                "notifications.html" -> "Напоминания об окончании подписки"
                else -> "Мои подарки и активация"
            }
            add(services, menuRow(title, description) {
                openOfficialPage(target)
            }, 3)
            if (target != "gifts.html") {
                add(services, ServerListVisual.separator(this), 2)
            }
        }

        val local = card()
        add(body, local, 13)
        add(local, tag("ПРИЛОЖЕНИЕ И БЕЗОПАСНОСТЬ"))
        add(local, t("Настройки устройства", 18f, white, true), 8)
        for ((target, label, description) in listOf(
            Triple(Page.ACCOUNT, "VPN-профиль и подписка",
                "Импортировать ссылку и управлять устройством"),
            Triple(Page.SECURITY, "Защита",
                "Kill Switch, исключения и состояние сети"),
            Triple(Page.DEVICES, "Этот Android", "Платформа и устройство"),
            Triple(Page.DIAGNOSTICS, "Диагностика",
                "Проверить работу туннеля и подключение"),
            Triple(Page.SETTINGS, "Настройки VainahVPN",
                "Сеть, обновления и параметры")
        )) {
            add(local, menuRow(label, description) {
                page = target
                render()
            }, 3)
            if (target != Page.SETTINGS) {
                add(local, ServerListVisual.separator(this), 2)
            }
        }
        add(local, t(
            "Вход, кабинет и каталог тарифов работают нативно. " +
                "Только выбранная оплата открывает сайт.",
            11f, grey), 12)
    }

    private fun refreshServers(manual: Boolean) {
        if (source.savedLink() == null) {
            if (manual) popup("Сначала сохрани VPN-профиль.")
            return
        }
        // A running tunnel must never prevent new LTE nodes from appearing.
        // The current tunnel remains untouched; changes affect the NEXT connect.
        if (!manual && VpnConnectionState.read(this).phase == VpnConnectionState.STARTING)
            return
        nextAutoRefresh = SystemClock.elapsedRealtime() +
            SubscriptionRefreshPolicy.NORMAL_MS
        val started = source.refresh { result ->
            result.onSuccess { fresh ->
                val updated = ServerListReconciler.unique(fresh)
                if (updated != nodes) {
                    invalidateServerProbes()
                    nodes = updated
                    selected = ServerListReconciler.preserve(selected, nodes)
                        ?.takeIf { SubscriptionNodeSupport.canConnect(it.uri) }
                        ?: nodes.firstOrNull { SubscriptionNodeSupport.canConnect(it.uri) }
                }
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

    /** The background WorkManager worker refreshes the encrypted cache.
     * Bring any new entries into the UI without reopening the app or altering
     * the active VPN tunnel. Avoid rebuilding an EditText while user types.
     */
    private fun reloadBackgroundSubscription() {
        val now = SystemClock.elapsedRealtime()
        if (now - lastCacheCheckElapsedMs < 15_000L || source.busy ||
            currentFocus is EditText) return
        lastCacheCheckElapsedMs = now
        val latest = source.cachedNodes()
        if (latest.isEmpty() || latest == nodes) return
        invalidateServerProbes()
        nodes = latest
        selected = ServerListReconciler.preserve(selected, nodes)
            ?.takeIf { SubscriptionNodeSupport.canConnect(it.uri) }
            ?: nodes.firstOrNull { SubscriptionNodeSupport.canConnect(it.uri) }
        cacheMessage = "Подписка обновлена автоматически: ${nodes.size} серверов"
        render()
    }

    private fun maybeRefresh() {
        if (source.busy) return
        val link = source.savedLink() ?: return
        val phase = VpnConnectionState.read(this).phase
        if (SubscriptionRefreshPolicy.shouldRefreshDuringSession(
                SystemClock.elapsedRealtime(), nextAutoRefresh,
                phase, SubscriptionInput.isDirectKey(link)))
            refreshServers(false)
    }

    private fun connect() {
        if (VpnConnectionState.read(this).canDisconnect) { disconnect(); return }
        if (!EngineRegistry.active.ready) {
            popup("VPN-движок libbox не установлен. Трафик не защищён.")
            return
        }
        val node = selected ?: run {
            popup("Нет выбранного совместимого сервера. XHTTP-узлы " +
                "видны в списке, но пока не поддерживаются текущим libbox.")
            return
        }
        if (!SubscriptionNodeSupport.canConnect(node.uri)) {
            popup("Эта конфигурация пока не поддерживается движком VainahVPN.")
            return
        }
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
    private fun updatePowerPulse(phase: String) {
        val orb = powerOrb
        if (orb == null || phase != VpnConnectionState.STARTING) {
            pulseAnimator?.cancel()
            pulseAnimator = null
            orb?.scaleX = 1f
            orb?.scaleY = 1f
            return
        }
        if (pulseAnimator != null) return
        pulseAnimator = ValueAnimator.ofFloat(1f, 1.065f).apply {
            duration = 920L
            repeatCount = ValueAnimator.INFINITE
            repeatMode = ValueAnimator.REVERSE
            addUpdateListener { frame ->
                val size = frame.animatedValue as Float
                powerOrb?.scaleX = size
                powerOrb?.scaleY = size
            }
            start()
        }
    }

    private fun updateConnection() {
        val snapshot = VpnConnectionState.read(this)
        val serviceRunning = VainahVpnService.runningInProcess
        val underlay = VpnUnderlayStatus.read(this)
        val network = when(underlay.transport) {
            "wifi" -> "Wi-Fi"
            "cellular" -> "4G / 5G"
            "ethernet" -> "Ethernet"
            else -> "Сеть не определена"
        }
        networkStatusView?.text = "Физическая сеть: " + network +
            if (underlay.validated) " · Android: подтверждена" else
                " · Android: не подтверждена"
        updatePowerPulse(snapshot.phase)
        val connected = snapshot.canDisconnect
        stateView?.text = when (snapshot.phase) {
            VpnConnectionState.ONLINE -> "Туннель запущен"
            VpnConnectionState.TUN_READY -> "VPN-туннель активен"
            VpnConnectionState.STARTING -> "Подключение…"
            VpnConnectionState.FAILED -> "Ошибка подключения"
            else -> "Не подключено"
        }
        (powerOrb as? PowerOrbView)?.setVpnPhase(snapshot.phase)
        stateView?.setTextColor(if (page == Page.HOME) {
            if (connected) VainahDesign.green else ServerListVisual.textColor()
        } else if (connected) green else white)
        detailView?.text = if (snapshot.phase == VpnConnectionState.OFF)
            "Выбери локацию и проверь IP в браузере после подключения."
        else snapshot.detail.ifBlank { "Данные службы пока недоступны." }
        connectView?.text = if (connected) "Отключить VPN" else "Подключиться"
        val fresh = if (connected && serviceRunning)
            VpnTrafficStore.read(this) else null
        if (fresh == null && (!connected || !serviceRunning)) {
            trafficTimeline.clear()
        } else if (fresh != null) {
            trafficTimeline.record(SystemClock.elapsedRealtime(),
                fresh.downlink, fresh.uplink)
        }
        trafficView?.text = when {
            !connected || !serviceRunning ->
                "График и статистика появятся после подключения."
            fresh == null -> "Счётчики libbox временно недоступны."
            else -> "↓ " + VpnTrafficStore.format(fresh.downlink) +
                "/с    ↑ " + VpnTrafficStore.format(fresh.uplink) +
                "/с\\nЗа сеанс: ↓ " +
                VpnTrafficStore.format(fresh.downlinkTotal) + " · ↑ " +
                VpnTrafficStore.format(fresh.uplinkTotal)
        }
        trafficChart?.show(trafficTimeline.snapshot())
    }
}
