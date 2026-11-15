package app.vainah.vpn

/**
 * A failed native engine may be restarted only for a user-initiated session
 * that had already established a TUN. Never retry a broken configuration
 * endlessly or silently reconnect after an explicit stop.
 */
object NativeRecoveryPolicy {
    const val MAX_RETRIES = 2

    fun shouldRetry(phase: String, retryCount: Int, hasActiveNode: Boolean): Boolean =
        hasActiveNode && retryCount in 0 until MAX_RETRIES &&
            (phase == VpnConnectionState.TUN_READY ||
                phase == VpnConnectionState.ONLINE)

    fun retryDelayMs(nextAttempt: Int): Long = when (nextAttempt) {
        1 -> 1_500L
        2 -> 5_000L
        else -> 0L
    }
}
