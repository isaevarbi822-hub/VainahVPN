package app.vainah.vpn

/**
 * Tracks only the currently visible VpnService instance inside this process.
 * An old Android service's asynchronous onDestroy/onRevoke must not publish
 * OFF/FAILED status or hide state belonging to its replacement.
 *
 * This is not an engine ownership/packet forwarding check: OwnedTunnelGate
 * separately serializes the native engine.
 */
class ForegroundServiceLease {
    private val lock = Any()
    private var current: Any? = null

    fun claim(service: Any) = synchronized(lock) {
        current = service
    }

    fun release(service: Any): Boolean = synchronized(lock) {
        if (current !== service) return@synchronized false
        current = null
        true
    }

    fun isCurrent(service: Any): Boolean = synchronized(lock) {
        current === service
    }

    fun hasCurrent(): Boolean = synchronized(lock) {
        current != null
    }
}
