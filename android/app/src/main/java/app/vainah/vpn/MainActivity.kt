package app.vainah.vpn

import androidx.browser.customtabs.CustomTabsIntent
import android.app.Activity
import android.app.AlertDialog
import android.Manifest
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.content.Intent
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.RadialGradient
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.text.InputType
import android.text.SpannableString
import android.text.Spanned
import android.text.method.PasswordTransformationMethod
import android.text.style.ForegroundColorSpan
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/** Site-matched Vainah VPN native UI. No WebView, bogus billing or fake tunnel. */
class MainActivity : Activity() {
    private enum class Tab { HOME, PLANS, ACCOUNT, HELP }
    private var tab = Tab.HOME
    private var deviceFilter = 0
    private var checkoutGeneration = 0
    private var checkoutStatus: NativeCheckout.Availability? = null
    // A return from hosted RollyPay checkout is NOT proof of payment.
    // It only prompts an authenticated server-side provider status refresh.
    private var checkoutReturnPending = false
    private var verifiedEmailHint: TextView? = null
    private var checkoutStatusView: TextView? = null
    private val checkoutButtons = mutableListOf<Pair<VainahPlan, Button>>()
    private var activeConnectionLabel: TextView? = null
    private var powerView: VainahPower? = null
    private var chosenServer = -1
    private var selectedNode: VainahNode? = null
    // Refresh only while the HOME screen is visible. A token also prevents
    // an old HTTP reply from rewriting a newer subscription's server list.
    private var serverRefreshButton: Button? = null
    private var serverRefreshInFlight = false
    private var serverRefreshGeneration = 0
    // ElapsedRealtime keeps automatic retry pacing independent of phone clock.
    // Manual refresh remains available, even during temporary provider denial.
    private var nextAutoServerRefreshElapsedMs = 0L
    private lateinit var mobileIdentity: NativeIdentity
    private lateinit var vault: SecureSubscription
    private lateinit var subscriptionHwid: SubscriptionHwid
    private val d get() = VainahDesign
    private val requestVpn = 4519
    private val refresher = Handler(Looper.getMainLooper())
    private var statusView: TextView? = null
    private var connectionDetailView: TextView? = null
    private var connectionMetaView: TextView? = null
    private var trafficView: TextView? = null
    private var connectionButton: Button? = null
    private var ipCheckButton: Button? = null
    private val refreshTask = object : Runnable {
        override fun run() {
            refreshConnectionStatus()
            maybeRefreshServerList()
            refresher.postDelayed(this, 1400)
        }
    }

    override fun onResume() {
        super.onResume()
        refresher.removeCallbacks(refreshTask)
        refresher.post(refreshTask)
        if(checkoutReturnPending){
            checkoutReturnPending=false
            refresher.postDelayed({
                if(!isFinishing && !isDestroyed)checkNativeOrder()
            },750)
        }
        if(tab==Tab.ACCOUNT)refreshVerifiedDeliveryEmail()
    }

    override fun onPause() {
        refresher.removeCallbacks(refreshTask)
        super.onPause()
    }

    override fun onDestroy() {
        serverRefreshGeneration++
        serverRefreshButton = null
        super.onDestroy()
    }

    private fun maybeRefreshServerList() {
        if (tab != Tab.HOME || serverRefreshInFlight) return
        val button = serverRefreshButton ?: return
        if (!button.isEnabled || vault.load() == null) return
        val saved = vault.load() ?: return
        if (SubscriptionRefreshPolicy.shouldAutoRefresh(
                SystemClock.elapsedRealtime(), nextAutoServerRefreshElapsedMs,
                VpnConnectionState.read(this).canDisconnect,
                SubscriptionInput.isDirectKey(saved))) {
            button.performClick()
        }
    }

    private fun refreshConnectionStatus() {
        var snapshot = VpnConnectionState.read(this)
        if ((snapshot.phase == VpnConnectionState.ONLINE ||
                snapshot.phase == VpnConnectionState.TUN_READY) &&
            !VainahVpnService.runningInProcess) {
            VpnConnectionState.failed(this, "VPN-служба завершилась, соединение не защищено")
            snapshot = VpnConnectionState.read(this)
        }
        val tunnelActive = snapshot.phase == VpnConnectionState.TUN_READY ||
            snapshot.phase == VpnConnectionState.ONLINE
        powerView?.setActive(tunnelActive)
        activeConnectionLabel?.text = when (snapshot.phase) {
            VpnConnectionState.TUN_READY, VpnConnectionState.ONLINE ->
                "● Туннель открыт · статус IP/DNS проверяй отдельно"
            VpnConnectionState.STARTING -> "◌ Подключаем VPN…"
            VpnConnectionState.FAILED -> "● VPN остановлен из-за ошибки"
            else -> "○ VPN отключён"
        }
        activeConnectionLabel?.setTextColor(
            if (tunnelActive) d.green else if (snapshot.phase == VpnConnectionState.FAILED)
                Color.rgb(250,157,154) else d.muted
        )
        statusView?.text = when (snapshot.phase) {
            VpnConnectionState.STARTING -> "Подключаемся…"
            VpnConnectionState.TUN_READY -> if (snapshot.detail.startsWith("VPN-туннель запущен;"))
                "Туннель активен · проверь браузер" else "Проверяем интернет…"
            VpnConnectionState.ONLINE -> "VPN · HTTPS-проба успешна"
            VpnConnectionState.FAILED -> "VPN не подключён"
            else -> "Не подключено"
        }
        val diagnosticCode = getSharedPreferences("vpn_diagnostics", MODE_PRIVATE)
            .getString("vpn_probe_reason", null)
        connectionDetailView?.text = when (snapshot.phase) {
            VpnConnectionState.ONLINE ->
                "HTTPS-проба службы успешна. Интернет в браузере, внешний IP и DNS ещё требуют отдельной проверки."
            VpnConnectionState.STARTING, VpnConnectionState.TUN_READY ->
                snapshot.detail + if (snapshot.phase == VpnConnectionState.TUN_READY &&
                    snapshot.detail.startsWith("VPN-туннель запущен;") &&
                    !diagnosticCode.isNullOrBlank())
                    "\nДиагностика: $diagnosticCode" else ""
            VpnConnectionState.FAILED -> snapshot.detail
            else -> if (EngineRegistry.active.ready)
                "Выбери локацию, подключись и проверь свой IP в браузере."
                else "VPN-движок пока не установлен. Трафик не защищён."
        }
        trafficView?.text = if (snapshot.canDisconnect) {
            val traffic = VpnTrafficStore.read(this)
            if (traffic == null) "Трафик libbox: счётчики пока недоступны"
            else "Скорость ↓ ${VpnTrafficStore.format(traffic.downlink)}/с" +
                " · ↑ ${VpnTrafficStore.format(traffic.uplink)}/с" +
                "\nЗа сеанс ↓ ${VpnTrafficStore.format(traffic.downlinkTotal)}" +
                " · ↑ ${VpnTrafficStore.format(traffic.uplinkTotal)}"
        } else "Статистика появится после подключения"
        connectionMetaView?.text =
            if (snapshot.server.isNotBlank() && snapshot.phase != VpnConnectionState.OFF) {
                "Сервер: ${snapshot.server}" +
                    if (snapshot.tcpLatencyMs >= 0)
                        " · TCP медиана ${snapshot.tcpLatencyMs} мс" else " · задержка неизвестна"
            } else selectedNode?.let { "Выбрано: ${it.label}" }
                ?: "Выбери сервер из подписки"
        ipCheckButton?.visibility = if (snapshot.canDisconnect) View.VISIBLE else View.GONE
        connectionButton?.text = if (snapshot.canDisconnect) "Отключить VPN"
            else "Подключиться"
    }

    private fun stopTunnel() {
        startService(Intent(this, VainahVpnService::class.java).apply {
            action = VainahVpnService.ACTION_DISCONNECT
        })
        // UI update is driven by actual service-owned status.
        refresher.postDelayed({ refreshConnectionStatus() }, 300)
    }
    private fun dp(n: Int) = (resources.displayMetrics.density * n).toInt()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        vault = SecureSubscription(this)
        subscriptionHwid = SubscriptionHwid(this)
        mobileIdentity = NativeIdentity(this)
        tab = savedInstanceState?.getString("page")?.let {
            runCatching { Tab.valueOf(it) }.getOrNull()
        } ?: Tab.HOME
        deviceFilter = savedInstanceState?.getInt("devices") ?: 0
        window.statusBarColor = d.background
        window.navigationBarColor = d.background
        renderPage()
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 4520)
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString("page", tab.name)
        outState.putInt("devices", deviceFilter)
        super.onSaveInstanceState(outState)
    }

    private fun shape(start: Int, end: Int = start, radius: Float = 22f,
                      border: Int = d.border): GradientDrawable =
        GradientDrawable(GradientDrawable.Orientation.TL_BR, intArrayOf(start, end)).apply {
            cornerRadius = radius * resources.displayMetrics.density
            setStroke(dp(1), border)
        }

    private fun column(): LinearLayout = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    private fun row(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
    }
    private fun add(parent: LinearLayout, child: View, top: Int = 0) {
        parent.addView(child, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply { topMargin = dp(top) })
    }
    private fun text(value: String, size: Float = 14f, color: Int = d.ink,
                     bold: Boolean = false): TextView = TextView(this).apply {
        this.text = value; textSize = size; setTextColor(color)
        if (bold) typeface = Typeface.create("sans-serif", Typeface.BOLD)
        setLineSpacing(dp(2).toFloat(), 1.04f)
        setPadding(0, dp(2), 0, dp(2))
    }
    private fun overline(value: String) = text(value,10f,d.purple,true).apply { letterSpacing = .12f }
    private fun panel(featured: Boolean = false): LinearLayout = column().apply {
        background = if(featured) shape(d.previewTop,d.previewBottom,23f,d.purple)
                     else shape(Color.rgb(30,34,57),Color.rgb(17,23,37),23f)
        setPadding(dp(20),dp(20),dp(20),dp(21))
    }
    private fun action(title: String, primary: Boolean = false): Button = Button(this).apply {
        text = title; isAllCaps = false; textSize = 13f
        typeface = Typeface.create("sans-serif", Typeface.BOLD)
        setTextColor(if(primary) Color.rgb(18,13,34) else d.ink)
        background = if(primary) shape(Color.rgb(212,185,255),Color.rgb(145,113,255),14f,d.purple)
                     else shape(d.surface2,d.surface2,14f,Color.rgb(65,70,95))
        minHeight = dp(49); contentDescription = title
    }
    private fun switch(destination: Tab) { tab = destination; renderPage() }
    private fun openSite(page: String) {
        if (!page.matches(Regex("[a-z-]+\\.html"))) return
        startActivity(Intent(Intent.ACTION_VIEW,Uri.parse(
            "https://vainahvpnbot0.netlify.app/" + page
        )))
    }
    private fun notice(message: String) {
        AlertDialog.Builder(this).setTitle("Vainah VPN").setMessage(message)
            .setPositiveButton("Понятно",null).show()
    }

    private fun renderPage() {
        // Invalidate previous UI/network callbacks whenever changing pages.
        serverRefreshGeneration++
        serverRefreshButton = null
        serverRefreshInFlight = false
        checkoutGeneration++
        checkoutButtons.clear()
        checkoutStatusView = null
        activeConnectionLabel = null
        powerView = null
        statusView = null
        connectionDetailView = null
        connectionMetaView = null
        trafficView = null
        connectionButton = null
        ipCheckButton = null
        val root = column().apply { setBackgroundColor(d.background) }
        val scroll = ScrollView(this).apply {
            isFillViewport = true; isVerticalScrollBarEnabled = false
        }
        val body = column().apply { setPadding(dp(16),dp(18),dp(16),dp(32)) }
        scroll.addView(body)
        root.addView(scroll,LinearLayout.LayoutParams(-1,0,1f))
        root.addView(bottomBar(),LinearLayout.LayoutParams(-1,dp(69)))
        setContentView(root)
        brandHeader(body)
        when(tab) {
            Tab.HOME -> home(body)
            Tab.PLANS -> plans(body)
            Tab.ACCOUNT -> account(body)
            Tab.HELP -> help(body)
        }
        add(body,text("VAINAH VPN · ${BuildConfig.VERSION_NAME} · Android",11f,d.muted),26)
    }

    private fun brandHeader(parent: LinearLayout) {
        val header = row()
        header.addView(VainahMark(this),LinearLayout.LayoutParams(dp(44),dp(44)))
        val brand = column().apply { setPadding(dp(12),0,0,0) }
        add(brand,text("VAINAH VPN",16f,d.ink,true).apply { letterSpacing=.07f })
        add(brand,text("ТВОЁ СОЕДИНЕНИЕ. ТВОИ ПРАВИЛА.",9f,d.muted,true))
        header.addView(brand,LinearLayout.LayoutParams(0,-2,1f))
        add(parent,header)
    }
    private fun intro(parent: LinearLayout,kicker: String,heading: String,
                      description: String,emphasis: String="") {
        add(parent,overline("●  "+kicker),29)
        val title = text(heading,35f,d.ink,true).apply {
            letterSpacing = -.045f
            if (emphasis.isNotEmpty() && heading.contains(emphasis)) {
                val start = heading.lastIndexOf(emphasis)
                val s = SpannableString(heading)
                s.setSpan(ForegroundColorSpan(d.purple),start,
                    start+emphasis.length,Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
                setText(s)
            }
        }
        add(parent,title,12)
        add(parent,text(description,13f,d.muted),9)
    }
    private fun home(parent: LinearLayout) {
        add(parent,overline("МОЙ VPN  /  ПАНЕЛЬ УПРАВЛЕНИЯ"),20)
        add(parent,text("VPN под контролем.",29f,d.ink,true),8)
        add(parent,text("Подключение, локации и скорость — всё рядом.",
            12f,d.muted),5)

        val preview=panel(true)
        add(parent,preview,20)
        val bar=row()
        bar.addView(overline("✦ VAINAH VPN"),
            LinearLayout.LayoutParams(0,-2,1f))
        val liveLabel=text("○ VPN отключён",11f,d.muted,true).apply {
            gravity=Gravity.END
        }
        activeConnectionLabel=liveLabel
        bar.addView(liveLabel)
        add(preview,bar)
        add(preview,overline("УПРАВЛЕНИЕ ТУННЕЛЕМ"),13)

        // Status, power and server fit in one compact card even on small phones.
        // Both power and CTA invoke the existing VpnService lifecycle.
        val statusRow=row()
        val power=VainahPower(this).apply {
            contentDescription="Подключиться к VPN"
            isClickable=true;isFocusable=true
            setOnClickListener { requestConnection() }
        }
        powerView=power
        statusRow.addView(power,LinearLayout.LayoutParams(dp(112),dp(112)))
        val summary=column().apply { setPadding(dp(13),0,0,0) }
        val currentStatus=text("Не подключено",23f,d.ink,true).apply {
            maxLines=2
        }
        statusView=currentStatus
        add(summary,currentStatus)
        val stateDetail=text("",11f,d.muted).apply { maxLines=4 }
        connectionDetailView=stateDetail
        add(summary,stateDetail,6)
        statusRow.addView(summary,LinearLayout.LayoutParams(0,-2,1f))
        add(preview,statusRow,12)

        val stateMeta=text("",12f,d.sky).apply { maxLines=2 }
        connectionMetaView=stateMeta
        add(preview,stateMeta,8)
        val connect=action("Подключиться",true)
        add(preview,connect,13)
        connectionButton=connect
        connect.setOnClickListener { requestConnection() }
        val ipButton=action("Проверить внешний IP ↗")
        ipCheckButton=ipButton
        add(preview,ipButton,8)
        ipButton.setOnClickListener {
            startActivity(Intent(Intent.ACTION_VIEW,
                Uri.parse("https://www.cloudflare.com/cdn-cgi/trace")))
        }

        val statisticsPanel=panel()
        add(parent,statisticsPanel,14)
        add(statisticsPanel,overline("СКОРОСТЬ И ТРАФИК"))
        val trafficStatus=text("Статистика появится после подключения",13f,d.ink)
        trafficView=trafficStatus
        add(statisticsPanel,trafficStatus,8)
        add(statisticsPanel,text("Показатели поступают из libbox.",11f,d.muted),5)

        // Locations are shown before privacy tests; service code is unchanged.
        val servers=panel()
        add(parent,servers,14)
        val privacy = panel()
        add(parent,privacy,16)
        add(privacy,overline("ЦЕНТР ПРИВАТНОСТИ"))
        add(privacy,text("Проверь маршруты и DNS",20f,d.ink,true),8)
        val externalCheck = text(
            "Тесты открываются во внешнем браузере; сайты увидят твой публичный IP. " +
                "Они не дают абсолютной гарантии отсутствия утечек.",
            11f,d.muted)
        add(privacy, externalCheck, 8)
        val dnsTest = action("Проверить DNS-утечки ↗")
        add(privacy,dnsTest,12)
        dnsTest.setOnClickListener {
            startActivity(Intent(Intent.ACTION_VIEW,
                Uri.parse("https://www.dnsleaktest.com/")))
        }
        val ipv6Test = action("Проверить IPv6 ↗")
        add(privacy,ipv6Test,8)
        ipv6Test.setOnClickListener {
            startActivity(Intent(Intent.ACTION_VIEW,
                Uri.parse("https://test-ipv6.com/")))
        }
        val killSwitch = action("Защита при сбоях · настройки Android ↗")
        add(privacy,killSwitch,8)
        killSwitch.setOnClickListener {
            notice("В настройках Android VPN можно включить «Постоянный VPN» " +
                "и «Блокировать подключения без VPN» для Vainah VPN, если эти " +
                "пункты доступны. Это может отключать интернет, пока VPN не работает.")
            runCatching {
                startActivity(Intent(android.provider.Settings.ACTION_VPN_SETTINGS))
            }
        }
        refreshConnectionStatus()
        val vpnDiagnostics = getSharedPreferences("vpn_diagnostics", MODE_PRIVATE)
        val lastError = vpnDiagnostics.getString("last_failure", null)
        val lastStage = vpnDiagnostics.getString("last_stage", null)
        val interrupted = vpnDiagnostics.getBoolean("startup_pending", false)
        if (EngineRegistry.active.ready) {
            val copyDiagnostic = action("Скопировать безопасную диагностику")
            add(privacy, copyDiagnostic, 12)
            copyDiagnostic.setOnClickListener {
                val prefs = getSharedPreferences("vpn_diagnostics", MODE_PRIVATE)
                val report = VpnDiagnosticReport.create(
                    VpnConnectionState.read(this).phase,
                    prefs.getString("last_stage", null),
                    prefs.getString("vpn_probe_reason", null),
                    Build.VERSION.SDK_INT,
                    VainahVpnService.runningInProcess,
                    VpnConnectivity.androidVpnFacts(this)
                )
                val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clipboard.setPrimaryClip(ClipData.newPlainText("Vainah VPN diagnostics", report))
                notice("Коды состояния скопированы. VPN-ссылки, ключи и IP не включены.")
            }
        }
        if (EngineRegistry.active.ready) {
            if (interrupted && !lastStage.isNullOrBlank()) {
                add(privacy,text("Запуск VPN прервался на этапе: $lastStage",11f,d.muted),9)
            } else if (!lastError.isNullOrBlank()) {
                add(privacy,text("Последняя ошибка движка: $lastError",11f,d.muted),9)
            }
        }
        add(privacy,text("Диагностика использует Android и libbox.",11f,d.muted),13)
        val shortcuts = row().apply {
            background = shape(d.surface2,d.surface,18f)
            setPadding(dp(9),dp(12),dp(9),dp(12))
        }
        for ((caption,page) in listOf("Тарифы  ↗" to Tab.PLANS,
            "Кабинет  ↗" to Tab.ACCOUNT,"Поддержка  ↗" to Tab.HELP)) {
            val button = action(caption)
            shortcuts.addView(button,LinearLayout.LayoutParams(0,dp(54),1f).apply {
                marginEnd = dp(4)
            })
            button.setOnClickListener { switch(page) }
        }
        add(parent,shortcuts,15)

        add(servers,overline("СЕРВЕРЫ И КОНФИГУРАЦИИ"))
        add(servers,text("Твои локации",23f,d.ink,true),9)
        add(servers,text(if(vault.load()!=null)
            if (SubscriptionInput.isDirectKey(vault.load().orEmpty()))
                "Прямой VLESS-ключ: сервер загружается локально. Автообновление доступно для HTTPS-подписок."
            else "SUB и Xray JSON. Серверы обновляются каждые 5 минут, пока приложение открыто."
            else "Добавь HTTPS-подписку или собственный VLESS REALITY-ключ в кабинете.",
            12f,d.muted),7)
        val syncStatus = text("Список ещё не синхронизирован", 12f, d.muted)
        add(servers, syncStatus, 7)
        // Show which server answered 403, never the private URL/token.
        add(servers, text(
            SubscriptionOrigin.label(SubscriptionOrigin.fromLink(vault.load())),
            11f, d.muted), 6)
        val search = EditText(this).apply {
            hint = "Поиск страны или локации..."
            setSingleLine(true)
            inputType = InputType.TYPE_CLASS_TEXT
            textSize = 14f
            setTextColor(d.ink)
            setHintTextColor(d.muted)
            background = shape(d.surface2, d.surface2, 14f)
            setPadding(dp(15),dp(13),dp(15),dp(13))
            contentDescription = "Поиск среди доступных VPN локаций"
        }
        add(servers,search,13)
        val selectedLocation = text("Выбери сервер для подключения",12f,d.sky)
        add(servers,selectedLocation,9)
        val serverResults=column()
        add(servers,serverResults,8)
        val visibleNodes = mutableListOf<VainahNode>()
        val emptySearch = text("По запросу ничего не найдено",12f,d.muted).apply {
            visibility = View.GONE
        }
        add(servers,emptySearch,9)
        val applySearch = {
            val term = search.text.toString().trim().lowercase()
            var matched = 0
            for (i in visibleNodes.indices) {
                val visible = term.isBlank() ||
                    visibleNodes[i].label.lowercase().contains(term)
                serverResults.getChildAt(i)?.visibility =
                    if (visible) View.VISIBLE else View.GONE
                if (visible) matched++
            }
            emptySearch.visibility = if (visibleNodes.isNotEmpty() && matched == 0)
                View.VISIBLE else View.GONE
        }
        search.addTextChangedListener(object: TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) = Unit
            override fun afterTextChanged(s: Editable?) { applySearch() }
        })
        // Last successfully parsed H1 list is encrypted in Android Keystore,
        // so a temporary outage does not empty the whole home screen.
        val showNodes: (List<VainahNode>, Boolean) -> Unit = { incoming, fromCache ->
            val names = ServerListReconciler.unique(incoming)
            val previous = selectedNode
            val restored = ServerListReconciler.preserve(previous, names)
            selectedNode = restored
            chosenServer = if (restored == null) -1 else names.indexOf(restored)
            visibleNodes.clear()
            visibleNodes.addAll(names)
            selectedLocation.text = if (restored == null)
                "Выбери сервер для подключения" else "✓ Выбрано: ${restored.label}"
            serverResults.removeAllViews()
            refreshConnectionStatus()
            names.forEachIndexed { index, node ->
                val choice = action(if (node == restored) "✓ ${node.label}" else node.label)
                add(serverResults, choice, 7)
                choice.setOnClickListener {
                    chosenServer = index
                    selectedNode = node
                    selectedLocation.text = "✓ Выбрано: ${node.label}"
                    refreshConnectionStatus()
                    for (child in 0 until serverResults.childCount) {
                        val other = serverResults.getChildAt(child) as? Button ?: continue
                        val current = names[child]
                        other.text = if (current == node) "✓ ${current.label}" else current.label
                    }
                }
            }
            applySearch()
            syncStatus.text = if (fromCache)
                "Показаны ${names.size} ранее сохранённых локаций. Доступность H1Cloud не подтверждена."
            else if (SubscriptionInput.isDirectKey(vault.load().orEmpty()))
                "Прямой VLESS-ключ импортирован локально. Серверов: ${names.size}. Синхронизация подписки не выполняется."
            else if (previous != null && restored == null)
                "Обновлено: ${names.size} локаций. Старый сервер изменён — выбери другой."
            else
                "Обновлено: ${names.size} локаций. Выбор ${if (restored != null) "сохранён" else "доступен"}."
        }
        val cachedLink = vault.load()
        if (cachedLink != null) {
            val cached = vault.cachedServers(cachedLink)
            if (cached.isNotEmpty()) showNodes(cached, true)
        }
        val loadServers=action("Обновить серверы")
        serverRefreshButton = loadServers
        add(servers,loadServers,10)
        loadServers.setOnClickListener {
            if (serverRefreshInFlight) return@setOnClickListener
            val link=vault.load()
            if(link==null){notice("Сначала добавь HTTPS-подписку.");return@setOnClickListener}
            val generation = serverRefreshGeneration
            serverRefreshInFlight = true
            // Set the next automatic attempt even while this one is pending.
            // On 401/403/429 the actual retry interval is increased below.
            nextAutoServerRefreshElapsedMs =
                SystemClock.elapsedRealtime() + SubscriptionRefreshPolicy.NORMAL_MS
            loadServers.isEnabled=false
            syncStatus.text = "Обновляем список локаций…"
            Thread {
                val result=runCatching {
                    val fresh = SubscriptionServers.loadNodes(
                        link, subscriptionHwid.requestHeaders(), vault.userAgent()
                    )
                    // Keep only OS-encrypted credentials after a successful fetch.
                    vault.saveServerCache(link, fresh)
                    fresh
                }
                runOnUiThread {
                    // Schedule no aggressive retry when H1Cloud refuses access.
                    // A late response may still set pacing, but must never
                    // repaint a newer subscription or change its server list.
                    if (!isFinishing && !isDestroyed && vault.load() == link) {
                        nextAutoServerRefreshElapsedMs =
                            SubscriptionRefreshPolicy.nextAllowed(
                                SystemClock.elapsedRealtime(), result.exceptionOrNull())
                    }
                    // Never display a response from a previous screen or
                    // subscription, even if its network request finished last.
                    if (isFinishing || isDestroyed || tab != Tab.HOME ||
                        generation != serverRefreshGeneration ||
                        serverRefreshButton !== loadServers) return@runOnUiThread
                    serverRefreshInFlight = false
                    loadServers.isEnabled = true
                    if (vault.load() != link) {
                        syncStatus.text = "Подписка изменилась — обнови список ещё раз"
                        return@runOnUiThread
                    }
                    result.onSuccess { incoming ->
                        showNodes(incoming, false)
                    }.onFailure { error ->
                        // Never expose raw Java/HTTP errors or the bearer URL.
                        // A failed refresh must not erase working node selection.
                        syncStatus.text = SubscriptionLoadFailure.explain(error) +
                            if (visibleNodes.isNotEmpty())
                                " Показываем последний сохранённый список; проверь его актуальность."
                            else ""
                    }
                }
            }.start()
        }
        // Fetch when the screen is first opened, without reinstalling the app.
        if (vault.load()!=null) loadServers.post {
            if (serverRefreshButton === loadServers && tab == Tab.HOME) {
                val saved = vault.load()
                val fromDirectKey = saved != null &&
                    SubscriptionInput.isDirectKey(saved)
                val canAutoRefresh = !VpnConnectionState.read(this).canDisconnect &&
                    SystemClock.elapsedRealtime() >= nextAutoServerRefreshElapsedMs
                if (fromDirectKey || canAutoRefresh) loadServers.performClick()
            }
        }
        val goProfile=action("Добавить или изменить подписку")
        add(servers,goProfile,12)
        goProfile.setOnClickListener{switch(Tab.ACCOUNT)}
        val stats=row().apply{background=shape(d.surface2,d.surface,18f)}
        for ((head,sub) in listOf("Локации" to "автообновл.",
                                 "VLESS" to "REALITY",
                                 "DNS/IPv6" to "проверка")) {
            val box=column().apply{gravity=Gravity.CENTER}
            add(box,text(head,14f,d.ink,true).apply{gravity=Gravity.CENTER})
            add(box,text(sub,10f,d.muted).apply{gravity=Gravity.CENTER})
            stats.addView(box,LinearLayout.LayoutParams(0,dp(73),1f))
        }
        add(parent,stats,18)

        add(parent,overline("ЛИЧНЫЙ КАБИНЕТ"),28)
        val overview=panel()
        add(parent,overview,10)
        add(overview,text("Всё важное.\nВ одном месте.",27f,d.ink,true))
        add(overview,text("Подписка и срок · устройства · история покупок · VPN-доступ",
            12f,d.muted),9)
        val go=action("Открыть кабинет  ↗")
        add(overview,go,15);go.setOnClickListener{switch(Tab.ACCOUNT)}
        val help=panel()
        add(parent,help,13)
        add(help,text("Центр поддержки",21f,d.ink,true))
        add(help,text("Проверка сервисов и инструкции для устройств.",
            12f,d.muted),9)
        val guide=action("Открыть помощь  ↗")
        add(help,guide,13);guide.setOnClickListener{switch(Tab.HELP)}

        val start=panel(true)
        add(parent,start,17)
        add(start,overline("ПЕРВЫЙ ЗАПУСК · 3 ПРОСТЫХ ШАГА"))
        for ((index,title,explain) in listOf(
            Triple("01","Войди в аккаунт","Открой настоящий сайт и выбери удобный способ входа."),
            Triple("02","Проверь подписку","Посмотри свой тариф, срок и доступ только после подтверждения."),
            Triple("03","Подключи сервер","Выбери локацию и проверь IP в браузере после подключения.")
        )) {
            add(start,text(index+"  "+title,16f,d.ink,true),13)
            add(start,text(explain,12f,d.muted),4)
        }
        val setup=action("Открыть мастер подключения ↗",true)
        add(start,setup,17)
        setup.setOnClickListener{openSite("device-center.html")}
        add(start,text(if (EngineRegistry.active.ready) "VPN-движок libbox доступен. Проверяй его на устройстве." else "Это предварительная версия интерфейса. VPN пока не подключается.",11f,d.muted),11)
    }
    private fun plans(parent: LinearLayout) {
        intro(parent,"ТАРИФЫ И ПОДПИСКИ",
            "Доступ на твоих условиях.",
            "Шесть тарифов Vainah VPN. Цены сверяются с официальным сервером перед оформлением.",
            "условиях.")
        val billingPanel = panel(true)
        add(parent,billingPanel,20)
        add(billingPanel,overline("ПЛАТЕЖИ · СТАТУС СЕРВЕРА"))
        val billingLabel = text("Проверяем доступность оформления…",13f,d.muted)
        checkoutStatusView = billingLabel
        add(billingPanel,billingLabel,11)
        add(billingPanel,text(
            "Оплата привязана к входу Clerk. RollyPay открывается в защищённой вкладке; " +
                "банк может подтвердить СБП. VPN выдаётся только после независимой проверки платежа.",
            11f,d.muted),8)
        val filter=panel()
        add(parent,filter,20)
        add(filter,overline("ФИЛЬТР ПО КОЛИЧЕСТВУ УСТРОЙСТВ"))
        val choices=row()
        for((value,name) in listOf(0 to "Все",3 to "3",6 to "6")) {
            val btn=action(name,value==deviceFilter)
            choices.addView(btn,LinearLayout.LayoutParams(0,dp(49),1f).apply {
                marginEnd=dp(6)
            })
            btn.setOnClickListener{deviceFilter=value;renderPage()}
        }
        add(filter,choices,10)
        val filtered=VainahPlans.all.filter{deviceFilter==0 || it.deviceLimit==deviceFilter}
        add(parent,text(filtered.size.toString()+" тарифов · безлимитный трафик",
            12f,d.muted),14)
        for(plan in filtered) {
            val tile=panel(plan.days==180 || plan.deviceLimit==6)
            add(parent,tile,13)
            add(tile,overline(if(plan.days==180) "✦ ПОПУЛЯРНЫЙ ВЫБОР" else plan.badge))
            val heading=row()
            heading.addView(text(plan.title,23f,d.ink,true),
                LinearLayout.LayoutParams(0,-2,1f))
            heading.addView(text(if(plan.deviceLimit==6) "6 устройств" else "3 устройства",
                11f,d.green,true))
            add(tile,heading,12)
            add(tile,text((if(plan.priceRub==1000) "1 000" else plan.priceRub.toString())+" ₽",
                36f,d.ink,true),6)
            val months = when(plan.days) {30->1;60->2;90->3;180->6;else->12}
            add(tile,text("≈ ${plan.priceRub / months} ₽/мес · ${plan.days} дней",
                12f,d.purple,true),4)
            add(tile,text("✓ Безлимитный трафик   ✓ VLESS REALITY",
                12f,d.muted),11)
            add(tile,text("✓ ${plan.deviceLimit} устройства   ✓ Синхронизация серверов",
                12f,d.muted),5)
            val buy=action("Проверяем возможность оплаты…",true)
            buy.isEnabled=false
            checkoutButtons.add(plan to buy)
            add(tile,buy,18)
            buy.setOnClickListener{ attemptCheckout(plan) }
        }
        val note=panel()
        add(parent,note,19)
        add(note,overline("УСЛОВИЯ ПОДПИСКИ"))
        add(note,text(
            "Оплата не списывается при просмотре тарифов. Доступ выдаёт сервер " +
                "только после подтверждённого платежа. Период, устройства и цена проверяются до оформления.",
            12f,d.muted),8)
        val compare=action("Сравнить тарифы и условия ↗")
        add(note,compare,13);compare.setOnClickListener{openSite("compare.html")}
        refreshBillingAvailability()
    }

    private fun refreshBillingAvailability() {
        val generation = checkoutGeneration
        checkoutStatusView?.text = "Проверяем состояние сервера оплаты…"
        Thread({
            val result = NativeCheckout.fetchAvailability()
            runOnUiThread {
                if (isFinishing || isDestroyed || tab != Tab.PLANS ||
                    checkoutGeneration != generation) return@runOnUiThread
                checkoutStatus = result
                val ready = BuildConfig.VAINAH_DIRECT_CHECKOUT_ENABLED && result.permitted
                val explanation = when {
                    !result.pricesMatch -> "Сервер оплаты недоступен или данные тарифов не совпадают. Оформление заблокировано."
                    !result.serverReady -> "RollyPay на сервере пока отключён. Заказы не создаются и деньги не списываются."
                    !BuildConfig.VAINAH_DIRECT_CHECKOUT_ENABLED ->
                        "Оплата в этой сборке отключена. Для версии Google Play нужен разрешённый платёжный сценарий."
                    else -> "Сервер оплаты готов. Покупка откроется внутри Vainah VPN в защищённой вкладке."
                }
                checkoutStatusView?.text = explanation
                checkoutButtons.forEach { (_, button) ->
                    button.isEnabled = ready
                    button.text = if(ready) "Оформить в Vainah VPN"
                        else "Оплата временно недоступна"
                }
            }
        }, "vainah-checkout-status").start()
    }

    private fun clerkLoggedIn():Boolean {
        if(!BuildConfig.VAINAH_CLERK_ENABLED)return false
        return runCatching {
            Class.forName("app.vainah.vpn.ClerkTokenProvider")
                .getMethod("loggedIn").invoke(null) as? Boolean ?: false
        }.getOrDefault(false)
    }

    // Must be called on a worker thread: Clerk may refresh a short-lived JWT.
    private fun clerkToken():String? {
        if(!BuildConfig.VAINAH_CLERK_ENABLED)return null
        return runCatching {
            Class.forName("app.vainah.vpn.ClerkTokenProvider")
                .getMethod("getToken").invoke(null) as? String
        }.getOrNull()
    }

    private fun refreshVerifiedDeliveryEmail() {
        val label=verifiedEmailHint?:return
        if(tab!=Tab.ACCOUNT)return
        if(!clerkLoggedIn()){
            label.text="○ Войди через Clerk. Для покупки понадобится проверенная почта."
            return
        }
        label.text="Проверяем подтверждённую почту в Clerk…"
        Thread {
            val outcome=runCatching {
                clerkToken()?.let{NativeIdentity.account(it)}
            }
            runOnUiThread {
                if(isFinishing||isDestroyed||tab!=Tab.ACCOUNT||
                   verifiedEmailHint!==label)return@runOnUiThread
                val account=outcome.getOrNull()
                label.text=when{
                    account==null || !account.authenticated ->
                        "Проверка аккаунта недоступна. Войди через Clerk повторно."
                    account.verifiedDeliveryEmail ->
                        "✓ Email подтверждён Clerk. Можно получать оплаченные VPN-ключи."
                    else ->
                        "● Вход подтверждён. Добавь email в профиле Clerk " +
                        "и подтверди его перед покупкой."
                }
            }
        }.start()
    }

    private fun startClerkLogin() {
        if(!BuildConfig.VAINAH_CLERK_ENABLED ||
           !ClerkPublicKey.isConfigured(BuildConfig.VAINAH_CLERK_PUBLISHABLE_KEY)){
            notice("Для входа Clerk нужен настоящий публичный ключ проекта. " +
                "Оплата в приложении недоступна.")
            return
        }
        runCatching {
            startActivity(Intent().setClassName(this,"app.vainah.vpn.ClerkLoginActivity"))
        }.onFailure{notice("Экран Clerk недоступен в этой сборке.")}
    }

    private fun attemptCheckout(plan: VainahPlan) {
        if(!BuildConfig.VAINAH_DIRECT_CHECKOUT_ENABLED ||
           checkoutStatus?.permitted != true) {
            notice("Платежи в приложении пока выключены. Деньги не списываются.")
            return
        }
        // Even a recently cached JWT can be expired. Ask Clerk for a fresh one.
        Thread {
            val token=clerkToken()
            runOnUiThread {
                if(isFinishing||isDestroyed)return@runOnUiThread
                if(token==null){
                    notice("Для покупки войди через Clerk в приложении.")
                    switch(Tab.ACCOUNT)
                    return@runOnUiThread
                }
                // Verify the current email state at Clerk BEFORE creating an invoice.
                Thread {
                    val readiness=runCatching { NativeIdentity.account(token) }
                    runOnUiThread {
                        if(isFinishing||isDestroyed)return@runOnUiThread
                        if(readiness.isFailure){
                            notice("Не удалось проверить Clerk-аккаунт. Проверь интернет.")
                            return@runOnUiThread
                        }
                        if(readiness.getOrNull()?.verifiedDeliveryEmail!=true){
                            notice("Подтверди email в Clerk перед покупкой, " +
                                "чтобы подписка пришла именно тебе.")
                            switch(Tab.ACCOUNT)
                            return@runOnUiThread
                        }
                        confirmNativeCheckout(plan,token)
                    }
                }.start()
            }
        }.start()
    }

    private fun confirmNativeCheckout(plan:VainahPlan,token:String) {
                AlertDialog.Builder(this)
                    .setTitle("Оформление: ${plan.title}")
                    .setMessage("К оплате ${plan.priceRub} ₽. После серверного подтверждения " +
                        "VPN станет доступен в приложении, а ссылка придёт на " +
                        "подтверждённую в Clerk почту. СБП может открыть банк.")
                    .setNegativeButton("Отмена",null)
                    .setPositiveButton("Продолжить"){_,_->
                        Thread {
                            // The server checks Clerk JWT again before creating an invoice.
                            val invoice=runCatching{NativeIdentity.createInvoice(token,plan.id)}
                            runOnUiThread{
                                if(isFinishing||isDestroyed)return@runOnUiThread
                                invoice.onSuccess {
                                    mobileIdentity.saveOrder(it.orderId)
                                    runCatching {
                                        // Pending only. Never trust a browser return as paid.
                                        CustomTabsIntent.Builder().setShowTitle(true)
                                            .setToolbarColor(d.background).build()
                                            .launchUrl(this,Uri.parse(it.payUrl))
                                        checkoutReturnPending=true
                                    }.onFailure{
                                        notice("Платёжная вкладка не открылась. " +
                                            "Заказ можно проверить в кабинете.")
                                    }
                                }.onFailure{
                                    notice("Оформление не запущено. Проверь Clerk и " +
                                        "подтверждённый email или повтори позже.")
                                }
                            }
                        }.start()
                    }.show()
    }

    private fun checkNativeOrder() {
        Thread {
            val token=clerkToken()
            // The latest Clerk-owned purchase is recovered server-side even
            // after reinstall. Do not trust a previous account's local order.
            val result=if(token==null)Result.failure(
                IllegalStateException("Clerk session missing"))
                else runCatching {
                    val id=NativeIdentity.latestOrder(token,mobileIdentity.lastOrder())
                        ?: throw IllegalStateException("No purchases in this Clerk account")
                    mobileIdentity.saveOrder(id)
                    NativeIdentity.readOrder(token,id)
                }
            runOnUiThread {
                if(isFinishing||isDestroyed)return@runOnUiThread
                result.onSuccess { order ->
                    if(order.status=="paid"&&order.delivery=="delivered"&&
                       order.subscriptionUrl!=null) {
                        if(vault.save(order.subscriptionUrl)){
                            chosenServer=-1
                            selectedNode=null
                            notice("Оплата подтверждена сервером! VPN сохранён. " +
                                (if(order.emailState=="sent")"Письмо также отправлено."
                                 else "Письмо ещё доставляется."))
                        }else notice("Оплата подтверждена, но импорт VPN не удался.")
                    }else {
                        val status=when(order.status){
                            "awaiting_payment","created" -> "Ожидаем подтверждения RollyPay"
                            "paid" -> if(order.delivery=="retry") "Оплачено · сервер выдачи повторяет попытку"
                                else "Оплачено · готовим VPN"
                            "refunded","chargeback" -> "Возврат/оспаривание · нужна проверка поддержки"
                            "canceled","expired" -> "Счёт закрыт · VPN не выдавался"
                            else -> "Статус заказа: ${order.status}"
                        }
                        notice(status+". Проверку можно повторить в кабинете.")
                    }
                }.onFailure{notice("Не удалось проверить заказ этого Clerk-аккаунта. Повтори позже.")}
            }
        }.start()
    }

    private fun account(parent: LinearLayout) {
        intro(parent,"ЛИЧНЫЙ КАБИНЕТ",
            "Моя подписка.",
            "Данные о покупках доступны в защищённом кабинете сайта после входа.",
            "подписка.")
        val vaultCard=panel(true)
        add(parent,vaultCard,23)
        add(vaultCard,overline("МОЙ VPN-ПРОФИЛЬ"))
        val present=vault.load()!=null
        add(vaultCard,text(if(present)"✓ Профиль сохранён локально"
            else "Профиль не добавлен",20f,d.ink,true),12)
        add(vaultCard,text("Ссылка хранится на устройстве в Android Keystore. Это не является подтверждением оплаченной подписки.",
            12f,d.muted),8)
        add(vaultCard,text(
            SubscriptionOrigin.label(SubscriptionOrigin.fromLink(vault.load())),
            12f,d.muted),8)
        add(vaultCard,text(
            "API кабинета и заказов в этой сборке всё ещё использует Netlify. " +
            "Перенос мобильного API на Python/Render не завершён.",
            11f,d.muted),8)
        val input=EditText(this).apply{
            hint="https:// подписка или vless:// собственный ключ"
            setHintTextColor(d.muted);setTextColor(d.ink);textSize=13f
            inputType=InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine(true)
            background=shape(Color.rgb(14,21,38),Color.rgb(14,21,38),12f)
            setPadding(dp(14),dp(15),dp(14),dp(15))
            importantForAutofill=View.IMPORTANT_FOR_AUTOFILL_NO
        }
        add(vaultCard,input,15)
        val save=action("Добавить подписку",true)
        add(vaultCard,save,12)
        save.setOnClickListener{
            if(vault.save(input.text.toString())){
                chosenServer = -1
                selectedNode = null
                input.text.clear();renderPage()
                notice("VPN-конфигурация защищённо сохранена в Android Keystore. Открой главную страницу и обнови серверы.")
            }else notice("Нужна полная HTTPS-ссылка или действительный VLESS TCP REALITY-ключ.")
        }
        val compareLink = action("Сравнить ссылку с Happ · локально")
        add(vaultCard,compareLink,9)
        compareLink.setOnClickListener {
            // The EditText holds user-pasted secret; only show SAME/DIFFERENT.
            // Never call the network or send a URL to logs/diagnostics.
            val comparison = SubscriptionLinkComparison.check(
                vault.load(), input.text.toString()
            )
            notice(SubscriptionLinkComparison.message(comparison))
        }
        add(vaultCard,text(
            "Вставь в поле выше полную ссылку из Happ и нажми «Сравнить». " +
                "Ничего не меняется, пока ты сам не нажмёшь «Добавить подписку».",
            11f,d.muted),8)
        val delete=action("Удалить с устройства")
        add(vaultCard,delete,9)
        delete.setOnClickListener{
            AlertDialog.Builder(this).setTitle("Удалить VPN-профиль?")
                .setMessage("Удалится только локально сохранённая ссылка.")
                .setNegativeButton("Отмена",null)
                .setPositiveButton("Удалить"){_,_->vault.delete();renderPage()}
                .show()
        }
        add(vaultCard,text("VPN-ссылку нельзя публиковать или отправлять посторонним.",
            11f,d.muted),13)
        val deviceCard = panel()
        add(parent, deviceCard, 14)
        add(deviceCard, overline("ДОСТУП К ПОДПИСКЕ · HWID"))
        add(deviceCard, text("Идентификатор Vainah VPN", 19f, d.ink, true), 8)
        add(deviceCard, text(
            "Некоторые панели требуют X-HWID для учёта устройств. " +
            "По умолчанию выключено. При включении H1Cloud получит случайный " +
            "постоянный ID этого приложения, версию Android и модель телефона. " +
            "Это может занять отдельное место в лимите устройств; ID Happ не копируется.",
            12f, d.muted), 8)
        val hwidButton = action(
            if (subscriptionHwid.isEnabled()) "✓ Отправка HWID включена · изменить"
            else "Отправка HWID выключена · включить")
        add(deviceCard, hwidButton, 12)
        hwidButton.setOnClickListener {
            val enabled = subscriptionHwid.isEnabled()
            AlertDialog.Builder(this)
                .setTitle(if (enabled) "Отключить HWID?" else "Включить отправку HWID?")
                .setMessage(if (enabled)
                    "Vainah VPN перестанет передавать идентификатор и модель телефона " +
                    "при загрузке HTTPS-подписки. Существующий слот на сервере это не удалит."
                    else "H1Cloud будет получать отдельный идентификатор Vainah VPN, " +
                    "версию Android и модель телефона только при обращении к твоей " +
                    "HTTPS-подписке. Это может расходовать ещё один слот устройства. " +
                    "Если сервер не разрешает этот HWID, ошибка 403 останется.")
                .setNegativeButton("Отмена", null)
                .setPositiveButton(if (enabled) "Отключить" else "Включить") { _, _ ->
                    if (subscriptionHwid.setEnabled(!enabled)) {
                        nextAutoServerRefreshElapsedMs = 0L
                        renderPage()
                        notice("Настройка сохранена. На главной странице нажми «Обновить серверы».")
                    } else notice("Не удалось сохранить настройку HWID.")
                }.show()
        }
        // A subscription backend may intentionally allow or deny clients by
        // User-Agent. Any alternate value must be entered by the user.
        // Protect it with the same Keystore key as their subscription.
        val agentCard = panel()
        add(parent, agentCard, 14)
        add(agentCard, overline("СОВМЕСТИМОСТЬ · USER-AGENT"))
        add(agentCard, text(
            if (vault.userAgent() == null) "Стандартный Vainah VPN"
            else "Пользовательский User-Agent включён",
            18f, d.ink, true), 7)
        add(agentCard, text(
            "Некоторые панели выдают подписки только разрешённым клиентам. " +
            "Укажи User-Agent, который твой провайдер разрешил использовать. " +
            "При его передаче сервер может увидеть идентификатор клиента. " +
            "Это не гарантирует снятия HTTP 403 или изменения лимита устройств.",
            12f, d.muted), 9)
        val agentInput = EditText(this).apply {
            hint = "User-Agent из настроек разрешённого клиента"
            setHintTextColor(d.muted); setTextColor(d.ink); textSize = 12f
            inputType = InputType.TYPE_CLASS_TEXT or
                InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
            setSingleLine(true)
            background = shape(Color.rgb(14,21,38), Color.rgb(14,21,38), 12f)
            setPadding(dp(14),dp(14),dp(14),dp(14))
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO
        }
        add(agentCard, agentInput, 8)
        val saveAgent = action("Применить User-Agent")
        add(agentCard, saveAgent, 8)
        saveAgent.setOnClickListener {
            if (vault.saveUserAgent(agentInput.text.toString())) {
                agentInput.text.clear()
                nextAutoServerRefreshElapsedMs = 0L
                notice("User-Agent сохранён зашифрованно. На главной обнови серверы.")
                renderPage()
            } else notice("Сначала сохрани VPN-ссылку. User-Agent: 5–180 латинских печатных символов, без ссылок и токенов.")
        }
        val resetAgent = action("Вернуть стандартный Vainah VPN")
        add(agentCard, resetAgent, 8)
        resetAgent.setOnClickListener {
            vault.resetUserAgent()
            nextAutoServerRefreshElapsedMs = 0L
            renderPage()
            notice("Восстановлен стандартный User-Agent Vainah VPN.")
        }
        val cabinet=panel()
        add(parent,cabinet,16)
        add(cabinet,overline("ПОДПИСКА И ИСТОРИЯ"))
        add(cabinet,text("Тариф · срок · устройства · покупки",20f,d.ink,true),10)
        add(cabinet,text("Приложение пока не считывает личные покупки. Реальные данные после Telegram Login показывает сайт.",
            12f,d.muted),8)
        val web=action("Войти в личный кабинет ↗",true)
        add(cabinet,web,13);web.setOnClickListener{openSite("account.html")}
        val hub=action("Центр управления ↗")
        add(cabinet,hub,8);hub.setOnClickListener{openSite("hub.html")}

        val providers=panel()
        add(parent,providers,16)
        add(providers,overline("ВХОД С CLERK"))
        add(providers,text("Регистрация по email ИЛИ телефону",
            17f,d.ink,true),11)
        add(providers,text(if(clerkLoggedIn())
            "✓ Вход через Clerk подтверждён. Дополнительная почта " +
                "потребуется только перед покупкой VPN для доставки ключа."
            else "Выбери вход по почте или телефону. Код приходит только " +
                "на выбранный контакт. Международные номера доступны по коду страны.",
            12f,d.muted),9)
        val signIn=action(if(clerkLoggedIn())"Открыть профиль Clerk"
            else "Войти / зарегистрироваться через Clerk",true)
        add(providers,signIn,12)
        signIn.setOnClickListener{startClerkLogin()}
        val emailHint=text("Проверка статуса email…",12f,d.muted)
        verifiedEmailHint=emailHint
        add(providers,emailHint,12)
        val emailAction=action("Добавить / подтвердить email в Clerk")
        add(providers,emailAction,8)
        emailAction.setOnClickListener{startClerkLogin()}
        refresher.post { refreshVerifiedDeliveryEmail() }
        add(providers,text("Telegram и Яндекс пока используют независимую " +
            "веб-авторизацию; для покупок нужна подтверждённая сессия Clerk.",
            11f,d.muted),12)
        val orderStatus=action("Проверить оплату и получить VPN")
        add(providers,orderStatus,12)
        orderStatus.setOnClickListener{checkNativeOrder()}
    }
    private fun help(parent: LinearLayout) {
        intro(parent,"ЦЕНТР ПОДДЕРЖКИ",
            "Помощь всегда рядом.",
            "Инструкции для устройств, диагностика и состояние сервисов.",
            "рядом.")
        val links=listOf(
            Triple("◉  Диагностика VPN","Вход, импорт, скорость и подключение.","diagnostics.html"),
            Triple("◇  Статус сервисов","Проверка базы данных и H1Cloud.","status.html"),
            Triple("▣  Мои устройства","iPhone, iPad, Android и другие.","device-center.html"),
            Triple("?  Вопросы и ответы","Помощь с тарифами и подпиской.","help.html"),
            Triple("⛨  Безопасность","Защита аккаунта и VPN-конфигурации.","security.html")
        )
        for((title,detail,page) in links){
            val tile=panel()
            add(parent,tile,13)
            add(tile,text(title,19f,d.ink,true))
            add(tile,text(detail,12f,d.muted),8)
            val button=action("Открыть раздел  ↗")
            add(tile,button,13);button.setOnClickListener{openSite(page)}
        }
        val faq=panel(true);add(parent,faq,17)
        add(faq,overline("ЧТО НУЖНО ЗНАТЬ"))
        add(faq,text("Как проверить свою приватность?",18f,d.ink,true),10)
        add(faq,text("Проверь внешний IP, DNS и IPv6 после подключения. Никакой онлайн-тест не гарантирует отсутствие утечек во всех сетях.",
            12f,d.muted),8)
    }
    private fun bottomBar(): LinearLayout {
        val nav=row().apply{
            setBackgroundColor(d.surface);setPadding(dp(6),dp(6),dp(6),dp(6))
        }
        for((destination,icon,title) in listOf(
            Triple(Tab.HOME,"⌂","Главная"),
            Triple(Tab.PLANS,"▦","Тарифы"),
            Triple(Tab.ACCOUNT,"◇","Кабинет"),
            Triple(Tab.HELP,"?","Помощь")
        )){
            val selected=tab==destination
            val tile=column().apply{
                gravity=Gravity.CENTER
                background=if(selected)shape(Color.rgb(51,42,81),Color.rgb(51,42,81),
                    13f,Color.rgb(92,75,136))else null
                isClickable=true;isFocusable=true
                contentDescription=title+(if(selected)" — текущая вкладка"else "")
                setOnClickListener{switch(destination)}
            }
            add(tile,text(icon,20f,if(selected)d.purple else d.muted,true).apply{
                gravity=Gravity.CENTER
            })
            add(tile,text(title,10f,if(selected)d.ink else d.muted,selected).apply{
                gravity=Gravity.CENTER
            })
            nav.addView(tile,LinearLayout.LayoutParams(0,-1,1f).apply{marginEnd=dp(2)})
        }
        return nav
    }
    private fun requestConnection(){
        if (VpnConnectionState.read(this).canDisconnect) {
            stopTunnel()
            return
        }
        if(selectedNode == null){
            notice("Сначала выбери сервер из подписки H1Cloud.");return
        }
        if(vault.load()==null){
            notice("Сначала добавь HTTPS-ссылку подписки из личного кабинета.");return
        }
        if(!EngineRegistry.active.ready){
            notice("VPN-движок H1Cloud/VLESS пока не интегрирован. Подключение не установлено, трафик не защищён.");return
        }
        val consent=VpnService.prepare(this)
        if(consent!=null)startActivityForResult(consent,requestVpn)else startTunnel()
    }
    @Deprecated("Compatibility VPN permission callback")
    override fun onActivityResult(requestCode:Int,resultCode:Int,data:Intent?){
        super.onActivityResult(requestCode,resultCode,data)
        if(requestCode==requestVpn){
            if(resultCode==RESULT_OK)startTunnel()
            else notice("Разрешение Android на VPN не предоставлено.")
        }
    }
    private fun startTunnel(){
        if(!EngineRegistry.active.ready||vault.load()==null)return
        val selected=selectedNode?.uri ?: return
        val intent=Intent(this,VainahVpnService::class.java).apply{
            action=VainahVpnService.ACTION_CONNECT
            putExtra(VainahVpnService.EXTRA_SELECTED_VLESS,selected)
            putExtra(VainahVpnService.EXTRA_SELECTED_LABEL,selectedNode?.label.orEmpty())
        }
        if(Build.VERSION.SDK_INT>=26)startForegroundService(intent)else startService(intent)
    }
}

private class VainahMark(activity:Activity):View(activity){
    private val p=Paint(Paint.ANTI_ALIAS_FLAG)
    override fun onDraw(c:Canvas){
        super.onDraw(c)
        val w=width.toFloat();val h=height.toFloat()
        p.shader=android.graphics.LinearGradient(0f,0f,w,h,
            intArrayOf(Color.rgb(189,159,255),Color.rgb(101,60,224)),
            null,Shader.TileMode.CLAMP)
        c.drawRoundRect(0f,0f,w,h,w*.28f,h*.28f,p)
        p.shader=null;p.color=Color.WHITE
        p.style=Paint.Style.STROKE;p.strokeWidth=w*.105f
        p.strokeCap=Paint.Cap.ROUND;p.strokeJoin=Paint.Join.ROUND
        val mark=Path().apply{
            moveTo(w*.22f,h*.30f);lineTo(w*.50f,h*.76f);lineTo(w*.79f,h*.30f)
        }
        c.drawPath(mark,p)
        p.color=Color.rgb(209,247,255);p.strokeWidth=w*.055f
        c.drawPath(Path().apply{
            moveTo(w*.50f,h*.17f);lineTo(w*.65f,h*.44f);lineTo(w*.50f,h*.78f)
        },p)
        p.style=Paint.Style.FILL
    }
}

private class VainahPower(activity:Activity):View(activity){
    private val p=Paint(Paint.ANTI_ALIAS_FLAG)
    private var connected = false
    fun setActive(isActive: Boolean) {
        if (connected != isActive) {
            connected = isActive
            contentDescription = if (connected) "Туннель открыт. Нажми для отключения VPN"
                else "Нажми, чтобы подключиться к VPN"
            invalidate()
        }
    }
    override fun onDraw(c:Canvas){
        super.onDraw(c)
        val cx=width/2f;val cy=height/2f
        val radius=Math.min(width,height)*.45f
        p.shader=RadialGradient(cx,cy,radius,
            if (connected)
                intArrayOf(Color.rgb(22,99,83),Color.rgb(21,49,55),Color.TRANSPARENT)
            else intArrayOf(Color.rgb(75,54,130),Color.rgb(38,28,74),Color.TRANSPARENT),
            floatArrayOf(0f,.57f,1f),Shader.TileMode.CLAMP)
        c.drawCircle(cx,cy,radius,p)
        p.shader=null;p.style=Paint.Style.STROKE
        p.color=if(connected)Color.rgb(112,229,177) else Color.rgb(169,139,255)
        p.strokeWidth=width*.009f
        c.drawCircle(cx,cy,radius*.64f,p)
        p.color=if(connected)Color.rgb(172,255,220) else Color.rgb(204,182,255)
        p.strokeWidth=width*.035f
        p.strokeCap=Paint.Cap.ROUND
        val r=radius*.32f
        c.drawArc(RectF(cx-r,cy-r,cx+r,cy+r),-47f,274f,false,p)
        c.drawLine(cx,cy-r*1.28f,cx,cy,p)
        p.style=Paint.Style.FILL
    }
}
