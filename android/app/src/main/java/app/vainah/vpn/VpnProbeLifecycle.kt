package app.vainah.vpn

/**
 * Bounded diagnostic bookkeeping only: the VPN must not be disconnected
 * merely because its owning UID cannot self-probe through the TUN.
 */
internal object VpnProbeLifecycle {
    const val TIMEOUT_MS = 15_000L
    const val IN_PROGRESS = "in_progress"
    const val TIMEOUT = "probe_timeout"
    const val CHECKING_STAGE = "checking_vpn_https_egress"
    const val TIMEOUT_STAGE = "vpn_https_probe_timeout"

    fun shouldMarkTimedOut(
        serviceCurrent: Boolean,
        phase: String,
        stage: String?,
        reason: String?
    ): Boolean =
        serviceCurrent &&
            phase == VpnConnectionState.TUN_READY &&
            stage == CHECKING_STAGE &&
            reason == IN_PROGRESS
}
