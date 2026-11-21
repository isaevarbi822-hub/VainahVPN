package app.vainah.vpn

import android.net.VpnService
import io.nekohasekai.libbox.CommandClient
import io.nekohasekai.libbox.CommandClientHandler
import io.nekohasekai.libbox.CommandClientOptions
import io.nekohasekai.libbox.ConnectionEvents
import io.nekohasekai.libbox.Libbox
import io.nekohasekai.libbox.LogIterator
import io.nekohasekai.libbox.OutboundGroupItemIterator
import io.nekohasekai.libbox.OutboundGroupIterator
import io.nekohasekai.libbox.StatusMessage
import io.nekohasekai.libbox.StringIterator

/**
 * Uses native sing-box traffic stats, not estimates from phone network speed
 * indicators or Android UID traffic. No connection metadata is exported.
 */
internal class LibboxTrafficMonitor(private val service: VpnService) : CommandClientHandler {
    private val lock = Any()
    @Volatile private var enabled = false
    private var client: CommandClient? = null

    fun start() {
        enabled = true
        Thread({
            synchronized(lock) {
                if (!enabled) return@synchronized
                val options = CommandClientOptions().apply {
                    addCommand(Libbox.CommandStatus)
                    statusInterval = 1_000_000_000L
                }
                val observer = CommandClient(this, options)
                client = observer
                // Observer failures never end the VPN itself. A missing status
                // stream produces "unavailable" in the UI.
                runCatching { observer.connect() }.onFailure {
                    VpnTrafficStore.clear(service)
                }
            }
        }, "vainah-libbox-traffic-status").start()
    }

    fun stop() {
        enabled = false
        synchronized(lock) {
            runCatching { client?.disconnect() }
            client = null
        }
        VpnTrafficStore.clear(service)
    }

    override fun connected() = Unit
    override fun disconnected(message: String?) {
        synchronized(lock) {
            if (enabled) VpnTrafficStore.clear(service)
        }
    }
    override fun setDefaultLogLevel(level: Int) = Unit
    override fun clearLogs() = Unit
    override fun writeLogs(messageList: LogIterator?) = Unit
    override fun writeGroups(message: OutboundGroupIterator?) = Unit
    override fun writeOutbounds(message: OutboundGroupItemIterator?) = Unit
    override fun initializeClashMode(modeList: StringIterator?, currentMode: String?) = Unit
    override fun updateClashMode(newMode: String?) = Unit
    override fun writeConnectionEvents(events: ConnectionEvents?) = Unit

    override fun writeStatus(message: StatusMessage) {
        // Serialize with stop(): old status callbacks must not repopulate
        // cleared counters after a disconnect or a new VPN session.
        synchronized(lock) {
            if (!enabled) return
            VpnTrafficStore.publish(service, VpnTrafficStore.Sample(
                uplink = message.uplink,
                downlink = message.downlink,
                uplinkTotal = message.uplinkTotal,
                downlinkTotal = message.downlinkTotal
            ), message.trafficAvailable)
        }
    }
}
