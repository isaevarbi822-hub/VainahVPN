package app.vainah.vpn

/**
 * Short home-screen copy. Full, detailed errors remain in diagnostics.
 * Opening a TUN never proves a working VPN exit, browser traffic, or DNS safety.
 */
internal object VpnHomeStatusPresentation {
    fun heading(phase: String): String = when (phase) {
        VpnConnectionState.STARTING -> "Подключаем VPN…"
        VpnConnectionState.TUN_READY, VpnConnectionState.ONLINE ->
            "Туннель запущен"
        VpnConnectionState.FAILED -> "Ошибка VPN"
        else -> "VPN отключён"
    }

    fun detail(phase: String, explanation: String): String = when (phase) {
        VpnConnectionState.STARTING -> "Устанавливаем защищённый туннель."
        VpnConnectionState.TUN_READY ->
            if ("не прошла" in explanation.lowercase())
                "Проверка интернета не прошла · Открой диагностику."
            else "Интернет через VPN не подтверждён · Проверь в браузере."
        VpnConnectionState.ONLINE ->
            "Внешний IP и DNS не проверены · Открой диагностику."
        VpnConnectionState.FAILED ->
            "Подключение не удалось · Открой диагностику."
        else -> "Выбери сервер и подключись."
    }

    fun physicalNetwork(transport: String, validated: Boolean): String {
        val network = when (transport) {
            "wifi" -> "Wi-Fi"
            "cellular" -> "4G / 5G"
            "ethernet" -> "Ethernet"
            else -> "Не определена"
        }
        return "$network · Android: " +
            if (validated) "физическая сеть проверена" else "сеть не подтверждена"
    }
}
