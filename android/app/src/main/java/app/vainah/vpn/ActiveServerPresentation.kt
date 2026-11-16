package app.vainah.vpn

/**
 * The active VPN server and the next selected profile are not interchangeable.
 * Selecting a new list row must never silently relabel an existing TUN.
 */
object ActiveServerPresentation {
    private fun safeLabel(raw: String): String {
        val safe = raw.replace(Regex("[\\p{Cntrl}]"), " ").trim().take(60)
        return if (safe.isBlank() || safe.contains("://") ||
            safe.contains('@') || safe.contains('?') || safe.contains('#') ||
            Regex("[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-").containsMatchIn(safe)
        ) "VPN-сервер" else safe
    }

    fun requiresDisconnectBeforeSwitch(phase: String): Boolean =
        phase == VpnConnectionState.STARTING ||
            phase == VpnConnectionState.TUN_READY ||
            phase == VpnConnectionState.ONLINE

    fun homeLabel(
        phase: String,
        runningInProcess: Boolean,
        activeLabel: String?,
        nextSelectedLabel: String?
    ): String =
        if (runningInProcess && requiresDisconnectBeforeSwitch(phase))
            "Сейчас: " + safeLabel(activeLabel.orEmpty())
        else if (nextSelectedLabel.isNullOrBlank())
            "Выбери сервер"
        else "Выбран: " + safeLabel(nextSelectedLabel)
}
