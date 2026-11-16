package app.vainah.vpn

/**
 * Truthful, testable display policy for the native VPN home and monitoring UI.
 * Android network validation does not prove that traffic traverses the VPN.
 * Never synthesizes measured bandwidth, IP, ping, or tunnel success.
 */
object VpnLivePresentation {
    fun phaseLabel(phase: String): String = when (phase) {
        VpnConnectionState.ONLINE -> "Туннель запущен"
        VpnConnectionState.TUN_READY -> "VPN-туннель активен"
        VpnConnectionState.STARTING -> "Подключение…"
        VpnConnectionState.FAILED -> "Ошибка подключения"
        else -> "Не подключено"
    }

    fun networkStatus(transport: String, validated: Boolean): String {
        val network = when (transport) {
            "wifi" -> "Wi-Fi"
            "cellular" -> "4G / 5G"
            "ethernet" -> "Ethernet"
            else -> "Сеть не определена"
        }
        val validation = if (validated) "подтверждена" else "не подтверждена"
        return "Физическая сеть: $network · Android: $validation"
    }

    fun trafficText(
        connected: Boolean,
        serviceRunning: Boolean,
        sample: VpnTrafficStore.Sample?
    ): String = when {
        !connected || !serviceRunning ->
            "График и статистика появятся после подключения."
        sample == null -> "Счётчики libbox временно недоступны."
        else -> "↓ " + VpnTrafficStore.format(sample.downlink) +
            "/с    ↑ " + VpnTrafficStore.format(sample.uplink) +
            "/с\\nЗа сеанс: ↓ " +
            VpnTrafficStore.format(sample.downlinkTotal) + " · ↑ " +
            VpnTrafficStore.format(sample.uplinkTotal)
    }
}
