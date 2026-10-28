package app.vainah.vpn

/**
 * Serializes native VPN engine ownership and cancellation.
 *
 * Stop requests may arrive while a native open() is still executing.
 * The caller invalidates its session generation first; after open() returns
 * we re-check it under the same lock and immediately close a cancelled tunnel.
 *
 * Retaining ownership on a failed close prevents a new session from opening
 * on top of an engine which may still be forwarding packets.
 */
class OwnedTunnelGate {
    private val lock = Any()
    private var owner: Any? = null

    fun connect(
        session: Any,
        requested: () -> Boolean,
        open: () -> Result<Unit>,
        close: () -> Unit
    ): Result<Unit> = synchronized(lock) {
        fun stillRequested() = runCatching { requested() }.getOrDefault(false)

        if (!stillRequested()) {
            return@synchronized Result.failure(
                IllegalStateException("VPN connection was cancelled")
            )
        }
        // Even the same service must finish closing its previous tunnel first.
        if (owner != null) {
            return@synchronized Result.failure(
                IllegalStateException("Previous VPN session still active")
            )
        }

        // Experimental libbox cleans up partial native initialization on its
        // own connect failure. The owner gate handles successful opens only.
        val result = try {
            open()
        } catch (error: Exception) {
            Result.failure(error)
        }
        if (result.isFailure) return@synchronized result

        owner = session
        if (!stillRequested()) {
            try {
                close()
                owner = null
                return@synchronized Result.failure(
                    IllegalStateException("VPN connection was cancelled")
                )
            } catch (error: Exception) {
                // Keep the old owner, so a later disconnect can retry cleanup.
                return@synchronized Result.failure(
                    IllegalStateException("Cancelled VPN cleanup failed", error)
                )
            }
        }
        result
    }

    fun disconnect(session: Any, close: () -> Unit) = synchronized(lock) {
        if (owner !== session) return@synchronized
        // If close fails, retain the owner rather than allowing a second
        // tunnel to race an engine that might still be active.
        close()
        owner = null
    }
}
