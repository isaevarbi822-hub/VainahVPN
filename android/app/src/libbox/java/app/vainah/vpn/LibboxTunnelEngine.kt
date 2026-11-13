package app.vainah.vpn

import android.net.VpnService
import io.nekohasekai.libbox.CommandServer
import io.nekohasekai.libbox.CommandServerHandler
import io.nekohasekai.libbox.OverrideOptions
import io.nekohasekai.libbox.SystemProxyStatus

/**
 * Experimental libbox engine. No claim of protected traffic until Android
 * device tests verify DNS, IPv4/IPv6, reconnection, and the actual exit IP.
 */
class LibboxTunnelEngine : TunnelEngine {
    override val ready: Boolean = true
    @Volatile private var commandServer: CommandServer? = null
    @Volatile private var platform: LibboxAndroidPlatform? = null
    @Volatile private var trafficMonitor: LibboxTrafficMonitor? = null

    private fun stage(service: VpnService, name: String) {
        service.getSharedPreferences("vpn_diagnostics", android.content.Context.MODE_PRIVATE)
            .edit().putString("last_stage", name).putBoolean("startup_pending", true).commit()
    }

    @Synchronized
    override fun connect(service: VpnService, singBoxConfigJson: String): Result<Unit> =
        runCatching {
            check(commandServer == null) { "VPN is already running" }
            // Required by upstream libbox before baseContext/NewCommandServer.
            stage(service, "initializing_libbox_setup")
            LibboxNativeApi.setup(service)

            stage(service, "creating_command_handler")
            // libbox's callback belongs to the session that created it.
            // Never call disconnect() directly here: that bypasses the
            // process-wide OwnedTunnelGate and leaves UI state stale.
            val owner = service as? VainahVpnService
            val ownerGeneration = owner?.nativeSessionGeneration()
            val handler = object : CommandServerHandler {
                override fun serviceStop() {
                    if (owner != null && ownerGeneration != null) {
                        Thread({
                            owner.onNativeEngineStopped(ownerGeneration)
                        }, "vainah-libbox-native-stop").start()
                    }
                }
                override fun serviceReload() = Unit
                override fun getSystemProxyStatus() = SystemProxyStatus().apply {
                    available = false
                    enabled = false
                }
                override fun setSystemProxyEnabled(enabled: Boolean) {
                    throw UnsupportedOperationException("System proxy disabled")
                }
                override fun triggerNativeCrash() {
                    throw SecurityException("Native crash disabled")
                }
                override fun writeDebugMessage(message: String) = Unit
                override fun connectSSHAgent(): Int =
                    throw UnsupportedOperationException("SSH agent disabled")
            }
            stage(service, "creating_platform_bridge")
            val bridge = LibboxAndroidPlatform(service) { stage(service, it) }
            platform = bridge

            stage(service, "creating_libbox_command_server")
            val server = LibboxNativeApi.createCommandServer(handler, bridge)
            commandServer = server

            stage(service, "validating_libbox_config")
            LibboxNativeApi.validateConfiguration(singBoxConfigJson)
            stage(service, "starting_libbox_command_server")
            server.start()
            stage(service, "loading_libbox_service")
            server.startOrReloadService(singBoxConfigJson, OverrideOptions())
            stage(service, "verifying_android_tun")
            // libbox may establish the TUN on its own native callback thread
            // just after startOrReloadService returns. Avoid a false startup
            // failure while still failing closed if no TUN appears.
            val tunDeadline = android.os.SystemClock.elapsedRealtime() + 6000L
            while (!bridge.hasTun() &&
                android.os.SystemClock.elapsedRealtime() < tunDeadline) {
                Thread.sleep(60L)
            }
            // TUN establishment does not prove internet access.
            check(bridge.hasTun()) { "libbox did not request Android TUN" }
            // Status stream reports actual core traffic. No sampling of app
            // UID packets (which would incorrectly include subscription API).
            trafficMonitor = LibboxTrafficMonitor(service).also { it.start() }
        }.onFailure {
            disconnect()
        }

    @Synchronized
    override fun disconnect() {
        trafficMonitor?.stop()
        trafficMonitor = null
        val current = commandServer
        commandServer = null
        try { current?.closeService() } catch (_: Exception) {}
        try { current?.close() } catch (_: Exception) {}
        platform?.close()
        platform = null
    }
}
