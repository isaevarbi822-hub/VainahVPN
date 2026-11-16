package app.vainah.vpn

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.VpnService
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log

/**
 * Android foreground VPN service. TUN creation is NOT an internet success.
 * This service checks VPN-bound HTTPS and fails closed on unavailable egress.
 */
class VainahVpnService : VpnService() {
    companion object {
        const val ACTION_CONNECT = "app.vainah.vpn.CONNECT"
        const val EXTRA_SELECTED_VLESS = "app.vainah.vpn.SELECTED_VLESS"
        const val EXTRA_SELECTED_LABEL = "app.vainah.vpn.SELECTED_LABEL"
        const val ACTION_DISCONNECT = "app.vainah.vpn.DISCONNECT"
        private val foregroundLease = ForegroundServiceLease()
        val runningInProcess: Boolean
            get() = foregroundLease.hasCurrent()
        private const val CHANNEL = "vainah_connection"
        private const val ID = 2103
    }

    @Volatile private var started = false
    @Volatile private var connectionGeneration = 0
    // Secrets remain in memory only while the user explicitly requested a VPN
    // session. No persistent reconnect tokens or background secret logs.
    @Volatile private var lastRequestedNode: String? = null
    @Volatile private var lastRequestedLabel = "Выбранный сервер"
    @Volatile private var recoveryAttempts = 0
    // True only between an unexpected native stop and a successfully
    // recreated TUN; allows a second bounded retry if recovery itself fails.
    @Volatile private var recoveringNativeSession = false
    private val recoveryHandler = Handler(Looper.getMainLooper())
    private var scheduledRecovery: Runnable? = null
    // Diagnostic timer only; never tears down a potentially working TUN.
    @Volatile private var probeWatchdog: Runnable? = null

    private fun startProbeWatchdog(generation: Int): Runnable {
        val job = Runnable {
            if (!isCurrentAttempt(generation)) return@Runnable
            val prefs = getSharedPreferences("vpn_diagnostics", MODE_PRIVATE)
            if (!VpnProbeLifecycle.shouldMarkTimedOut(
                    true, VpnConnectionState.read(this).phase,
                    prefs.getString("last_stage", null),
                    prefs.getString("vpn_probe_reason", null)
                )) return@Runnable
            // A slow/inaccessible self-probe is not a failed VPN session.
            prefs.edit()
                .putString("last_stage", VpnProbeLifecycle.TIMEOUT_STAGE)
                .putString("vpn_probe_reason", VpnProbeLifecycle.TIMEOUT)
                .putBoolean("startup_pending", false)
                .commit()
        }
        probeWatchdog = job
        recoveryHandler.postDelayed(job, VpnProbeLifecycle.TIMEOUT_MS)
        return job
    }

    private fun cancelProbeWatchdog(job: Runnable? = null) {
        if (job != null) {
            recoveryHandler.removeCallbacks(job)
            if (probeWatchdog === job) probeWatchdog = null
        } else {
            probeWatchdog?.let { recoveryHandler.removeCallbacks(it) }
            probeWatchdog = null
        }
    }

    // A recreated Android service can supersede this instance even before
    // the old onDestroy callback has been delivered. A generation check alone
    // cannot protect global connection state from the previous instance.
    private fun isCurrentAttempt(generation: Int): Boolean =
        generation == connectionGeneration && foregroundLease.isCurrent(this)

    /**
     * libbox calls serviceStop when the native command server stops.
     * Capture the generation BEFORE entering the native engine: a delayed
     * callback from an old session must not stop a replacement session.
     */
    internal fun nativeSessionGeneration(): Int = connectionGeneration

    @Synchronized
    internal fun onNativeEngineStopped(expectedGeneration: Int) {
        if (!NativeStopFence.shouldHandle(
                expectedGeneration, connectionGeneration, started,
                foregroundLease.isCurrent(this)
            )) return
        val snapshot = VpnConnectionState.read(this)
        val rawNode = lastRequestedNode
        if (NativeRecoveryPolicy.shouldRetry(
                snapshot.phase, recoveryAttempts, rawNode != null,
                recoveringNativeSession
            ) && rawNode != null) {
            // Invalidate all old callbacks BEFORE closing the failed engine.
            // Never leave a duplicate live TUN or reconnect after user STOP.
            val ticket = ++connectionGeneration
            val attempt = ++recoveryAttempts
            recoveringNativeSession = true
            VpnConnectionState.reconnecting(
                this, lastRequestedLabel, attempt, NativeRecoveryPolicy.MAX_RETRIES
            )
            VpnTrafficStore.clear(this)
            showNotification()
            Thread({
                val closed = runCatching {
                    EngineRegistry.disconnectOwned(this)
                }.isSuccess
                recoveryHandler.post {
                    if (!isCurrentAttempt(ticket)) return@post
                    if (!closed) {
                        VpnConnectionState.failed(this,
                            "Не удалось безопасно остановить VPN для восстановления.")
                        disconnect(userRequested = false)
                        return@post
                    }
                    val retry = Runnable {
                        scheduledRecovery = null
                        if (isCurrentAttempt(ticket) && started &&
                            lastRequestedNode == rawNode) {
                            checkpoint("service_received_connect")
                            launchTunnelAttempt(rawNode)
                        }
                    }
                    scheduledRecovery = retry
                    recoveryHandler.postDelayed(
                        retry, NativeRecoveryPolicy.retryDelayMs(attempt)
                    )
                }
            }, "vainah-native-safe-recovery").start()
            return
        }
        failure("native_engine_stopped", IllegalStateException("Native service stopped"))
        VpnConnectionState.failed(this,
            "VPN-движок остановился. Автовосстановление исчерпано или недоступно.")
        disconnect(userRequested = false)
    }

    // Synchronous checkpoints survive an abrupt native-process crash.
    private fun checkpoint(stage: String) {
        val editor = getSharedPreferences("vpn_diagnostics", MODE_PRIVATE).edit()
            .putString("last_stage", stage)
            .putBoolean("startup_pending", true)
        if (stage == VpnProbeLifecycle.CHECKING_STAGE) {
            editor.putString("vpn_probe_reason", VpnProbeLifecycle.IN_PROGRESS)
        }
        if (stage == "service_received_connect") {
            // Old DNS/HTTPS errors must not look like results from this run.
            editor.remove("vpn_probe_reason")
                .remove("last_failure").remove("last_failure_code")
        }
        editor.commit()
    }

    private fun completeStartup(probeReason: String) {
        // The successful HTTPS status must be explicit in the safe report.
        // This says nothing about another app's public IP or DNS behavior.
        val code = if (probeReason == "https_204") "https_204" else "unknown"
        getSharedPreferences("vpn_diagnostics", MODE_PRIVATE).edit()
            .putString("last_stage", "vpn_https_probe_success")
            .putString("vpn_probe_reason", code)
            .remove("last_failure_code")
            .putBoolean("startup_pending", false)
            .commit()
    }

    @Suppress("UNUSED_PARAMETER")
    private fun failure(stage: String, error: Throwable) {
        // Never log messages, endpoints or exception values. The only persisted
        // diagnostic is a fixed code derived from our own internal stage.
        val at = getSharedPreferences("vpn_diagnostics", MODE_PRIVATE)
            .getString("last_stage", null)
        val code = if (stage == "native_engine_stopped") {
            VpnFailureAdvisor.fromStage("native_engine_stopped").code
        } else VpnFailureAdvisor.fromStage(at).code
        Log.e("VainahVpn", "VPN stage failure: $code")
        getSharedPreferences("vpn_diagnostics", MODE_PRIVATE).edit()
            .putString("last_failure_code", code)
            .putBoolean("startup_pending", false)
            .commit()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_DISCONNECT -> {
                disconnect(userRequested = true)
                return START_NOT_STICKY
            }
            ACTION_CONNECT -> {
                if (started) return START_NOT_STICKY
                // Reset only local link observations for the new session;
                // an old Wi-Fi/cellular transition is not a new observation.
                VpnUnderlayStatus.reset(this)
                checkpoint("service_received_connect")
                val rawNode = intent.getStringExtra(EXTRA_SELECTED_VLESS).orEmpty()
                // A provider can issue a valid, current subscription containing
                // transport options rejected by this libbox build. These are
                // separate failures and must never prompt repeated payments.
                val rejection = VpnStartupPreflight.failureStage(
                    engineReady = EngineRegistry.active.ready,
                    subscriptionPresent = SecureSubscription(this).load() != null,
                    profileValid = runCatching {
                        VlessRealityConfig.profile(rawNode)
                    }.isSuccess
                )
                if (rejection != null) {
                    checkpoint(rejection)
                    val advice = VpnFailureAdvisor.fromStage(rejection)
                    getSharedPreferences("vpn_diagnostics", MODE_PRIVATE).edit()
                        .putString("last_failure_code", advice.code)
                        .putBoolean("startup_pending", false).commit()
                    VpnConnectionState.failed(this, advice.title)
                    stopSelf()
                    return START_NOT_STICKY
                }
                val label = intent.getStringExtra(EXTRA_SELECTED_LABEL)
                    ?.take(80)?.takeIf { it.isNotBlank() } ?: "Выбранный сервер"
                VpnConnectionState.starting(this, label)
                VpnTrafficStore.clear(this)
                try {
                    checkpoint("starting_foreground_notification")
                    startVisibleService()
                } catch (error: Exception) {
                    failure("foreground service", error)
                    VpnConnectionState.failed(this, "Не удалось запустить службу Android")
                    stopSelf()
                    return START_NOT_STICKY
                }
                lastRequestedNode = rawNode
                lastRequestedLabel = label
                recoveryAttempts = 0
                recoveringNativeSession = false
                launchTunnelAttempt(rawNode)
            }
        }
        return START_NOT_STICKY
    }

    /** Start one fenced connection attempt; used by initial connect and a
     * strictly bounded automatic recovery after unexpected native shutdown.
     */
    private fun launchTunnelAttempt(rawNode: String) {
        val generation = ++connectionGeneration
        Thread({
            try {
                // TCP reachability is measured outside the tunnel, not called VPN ping.
                checkpoint("resolving_h1cloud_before_vpn")
                val upstream = StartupRetryPolicy.execute(
                    stillRequested = { isCurrentAttempt(generation) },
                    connect = { VpnConnectivity.prepareUpstream(this, rawNode) }
                )
                val latency = upstream.tcpLatencyMs
                if (!isCurrentAttempt(generation)) return@Thread
                VpnConnectionState.latency(this, latency)
                showNotification()
                checkpoint("starting_libbox_native_engine")
                // libbox dials a numeric IP so the REALITY endpoint cannot
                // deadlock on bootstrap DNS after VPN routing starts.
                val resolvedConfig = VlessRealityConfig.profile(rawNode, upstream.numericAddress)
                val result = EngineRegistry.connectOwned(this, resolvedConfig) {
                    isCurrentAttempt(generation)
                }
                if (!isCurrentAttempt(generation)) return@Thread
                result.exceptionOrNull()?.let { throw it }
                recoveringNativeSession = false
                VpnConnectionState.tunnelCreated(this)
                showNotification()
                checkpoint(VpnProbeLifecycle.CHECKING_STAGE)
                val watchdog = startProbeWatchdog(generation)
                val probe = try {
                    VpnConnectivity.diagnoseTunnel(this)
                } finally {
                    cancelProbeWatchdog(watchdog)
                }
                if (!probe.reachable) {
                    // The VPN app's own process may be excluded from its TUN.
                    // A failed self-probe is NOT proof other apps lack internet.
                    // Keep the tunnel available for a real browser check, and
                    // retain a visible Stop action. Do not claim protection.
                    if (!isCurrentAttempt(generation)) return@Thread
                    getSharedPreferences("vpn_diagnostics", MODE_PRIVATE).edit()
                        .putString("last_stage", "vpn_https_probe_inconclusive")
                        .putString("vpn_probe_reason", probe.reason)
                        .putBoolean("startup_pending", false).commit()
                    VpnConnectionState.tunnelUnverified(this)
                    showNotification()
                    return@Thread
                }
                if (!isCurrentAttempt(generation)) return@Thread
                completeStartup(probe.reason)
                // An HTTPS request from the VPN app's own UID can
                // bypass the tunnel. Do not report ONLINE until
                // another app's traffic and exit IP are verified.
                VpnConnectionState.tunnelAwaitingBrowserValidation(this)
                showNotification()
            } catch (error: Throwable) {
                // A cancelled connection must NEVER overwrite the user's
                // deliberate OFF state, or shut down a newer generation.
                if (!isCurrentAttempt(generation)) return@Thread
                failure("VPN startup / internet verification", error)
                val failedStage = getSharedPreferences(
                    "vpn_diagnostics", MODE_PRIVATE
                ).getString("last_stage", null)
                // Show only a fixed, pre-reviewed diagnosis. Native exception
                // text may contain private server credentials.
                VpnConnectionState.failed(
                    this, VpnFailureAdvisor.fromStage(failedStage).title
                )
                disconnect(userRequested = false)
            }
        }, "vainah-vpn-connect").start()
    }

    private fun notification(): Notification {
        val state = VpnConnectionState.read(this)
        val latency = if (state.tcpLatencyMs >= 0)
            " · TCP до сервера ${state.tcpLatencyMs} мс" else ""
        val detail = when (state.phase) {
            VpnConnectionState.ONLINE -> "HTTPS-проба прошла · IP/DNS не проверены"
            VpnConnectionState.TUN_READY -> "Туннель активен · интернет не подтверждён"
            else -> "Устанавливаем соединение"
        }
        val stopIntent = Intent(this, VainahVpnService::class.java).apply {
            action = ACTION_DISCONNECT
        }
        val stopAction = PendingIntent.getService(this, 1, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val openAction = PendingIntent.getActivity(this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL)
            .setContentTitle("VainahVPN · ${state.server}")
            .setContentText("$detail$latency")
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setContentIntent(openAction)
            .setOnlyAlertOnce(true)
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Отключить", stopAction)
            .setOngoing(true)
            .build()
    }

    private fun showNotification() {
        if (started && foregroundLease.isCurrent(this)) getSystemService(NotificationManager::class.java)
            .notify(ID, notification())
    }

    private fun startVisibleService() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, "VainahVPN · соединение",
                NotificationManager.IMPORTANCE_LOW)
        )
        val notice = notification()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(ID, notice, ServiceInfo.FOREGROUND_SERVICE_TYPE_SYSTEM_EXEMPTED)
        } else startForeground(ID, notice)
        started = true
        foregroundLease.claim(this)
    }

    private fun disconnect(userRequested: Boolean) {
        connectionGeneration++
        cancelProbeWatchdog()
        scheduledRecovery?.let { recoveryHandler.removeCallbacks(it) }
        scheduledRecovery = null
        lastRequestedNode = null
        recoveringNativeSession = false
        val wasCurrentService = foregroundLease.release(this)
        if (wasCurrentService) VpnTrafficStore.clear(this)
        if (userRequested && wasCurrentService) VpnConnectionState.disconnected(this)
        if (started) {
            started = false
            stopForeground(STOP_FOREGROUND_REMOVE)
        }
        Thread({
            runCatching { EngineRegistry.disconnectOwned(this) }
                .onFailure { failure("engine shutdown", it) }
        }, "vainah-vpn-shutdown").start()
        stopSelf()
    }

    override fun onRevoke() {
        disconnect(userRequested = true)
        super.onRevoke()
    }

    override fun onDestroy() {
        connectionGeneration++
        cancelProbeWatchdog()
        scheduledRecovery?.let { recoveryHandler.removeCallbacks(it) }
        scheduledRecovery = null
        lastRequestedNode = null
        recoveringNativeSession = false
        val wasCurrentService = foregroundLease.release(this)
        // A superseded service must not mark the new service as failed.
        if (wasCurrentService && VpnConnectionState.read(this).canDisconnect) {
            VpnConnectionState.failed(this, "VPN-служба остановлена; защита не подтверждена")
        }
        if (started) {
            started = false
            runCatching { stopForeground(STOP_FOREGROUND_REMOVE) }
            Thread({ runCatching { EngineRegistry.disconnectOwned(this) } },
                "vainah-vpn-destroy").start()
        }
        super.onDestroy()
    }
}
