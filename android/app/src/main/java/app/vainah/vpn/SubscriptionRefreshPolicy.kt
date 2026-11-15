package app.vainah.vpn

/**
 * Conservative automatic refresh schedule: a deliberate manual refresh remains
 * possible, but a server rejecting requests must not be contacted repeatedly
 * whenever the user changes screens.
 *
 * Does not infer subscription expiry or manipulate HTTP authorisation.
 */
object SubscriptionRefreshPolicy {
    const val NORMAL_MS = 5 * 60 * 1000L
    private const val TRANSIENT_MS = 2 * 60 * 1000L
    private const val ACCESS_DENIED_MS = 30 * 60 * 1000L
    private const val RATE_LIMIT_MS = 15 * 60 * 1000L

    fun retryDelay(error: Throwable?): Long = when (error) {
        null -> NORMAL_MS
        is SubscriptionHttpStatus -> when (error.status) {
            401, 403 -> ACCESS_DENIED_MS
            429 -> RATE_LIMIT_MS
            in 500..599 -> TRANSIENT_MS
            else -> TRANSIENT_MS
        }
        else -> TRANSIENT_MS
    }

    fun shouldAutoRefresh(
        nowElapsedMs: Long,
        nextAllowedElapsedMs: Long,
        runningVpn: Boolean,
        isDirectKey: Boolean
    ): Boolean = !runningVpn && !isDirectKey && nowElapsedMs >= nextAllowedElapsedMs

    /** An established VPN should NOT freeze server-list updates. The only
     * excluded phase is startup, when an extra HTTPS request may interfere
     * with tunnel initialization. This changes no active server selection.
     */
    fun shouldRefreshDuringSession(
        nowElapsedMs: Long,
        nextAllowedElapsedMs: Long,
        vpnPhase: String,
        isDirectKey: Boolean,
    ): Boolean = shouldAutoRefresh(
        nowElapsedMs, nextAllowedElapsedMs,
        runningVpn = vpnPhase == VpnConnectionState.STARTING,
        isDirectKey = isDirectKey
    )

    fun nextAllowed(nowElapsedMs: Long, error: Throwable?): Long =
        nowElapsedMs + retryDelay(error)
}
