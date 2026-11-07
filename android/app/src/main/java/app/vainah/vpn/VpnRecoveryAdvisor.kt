package app.vainah.vpn

/**
 * Conservative guidance after a physical-network outage.
 * Android's underlay validation does NOT prove VPN tunnel egress.
 * Never reconnects or disables the VPN automatically.
 */
data class VpnRecoveryState(
    val vpnActive: Boolean,
    val transport: String,
    val validated: Boolean,
    val offlineDurationMs: Long?,
    val lastOutageMs: Long?,
)

data class VpnRecoveryAdvice(
    val code: String,
    val title: String,
    val message: String,
    val attention: Boolean,
)

object VpnRecoveryAdvisor {
    const val LONG_OUTAGE_MS = 30_000L
    const val MAX_TRACKED_MS = 86_400_000L

    fun advice(state: VpnRecoveryState): VpnRecoveryAdvice {
        if (!state.vpnActive) return VpnRecoveryAdvice(
            "vpn_off", "VPN сейчас не запущен",
            "Подключи VPN, если требуется проверить работу сети. Старые замеры не доказывают состояние текущего соединения.",
            false,
        )
        if (state.transport == "none") {
            val elapsed = state.offlineDurationMs
            return if (elapsed != null && elapsed >= LONG_OUTAGE_MS) {
                VpnRecoveryAdvice(
                    "underlay_long_outage", "Физическая сеть долго недоступна",
                    "Android не видит подходящую физическую сеть уже не менее 30 секунд. " +
                        "Проверь Wi-Fi или мобильные данные. Не оплачивай VPN повторно. " +
                        "После возвращения сети проверь браузер и маршруты VPN.",
                    true,
                )
            } else {
                VpnRecoveryAdvice(
                    "underlay_brief_outage", "Ожидание физической сети",
                    "Android пока не видит подходящую физическую сеть. " +
                        "Не перезапускай VPN многократно; дождись восстановления Wi-Fi или мобильных данных.",
                    false,
                )
            }
        }
        if (!state.validated) return VpnRecoveryAdvice(
            "underlay_unvalidated", "Сеть появилась, доступ не подтверждён",
            "Android видит физический интерфейс, но ещё не подтвердил доступ в интернет. " +
                "Это не доказательство неисправности VPN. Проверь обычную сеть и затем VPN.",
            false,
        )
        if ((state.lastOutageMs ?: 0L) >= LONG_OUTAGE_MS) return VpnRecoveryAdvice(
            "underlay_restored_after_outage", "Сеть восстановилась после долгого обрыва",
            "Android снова подтвердил физическую сеть. Проверь сайты через VPN " +
                "и при необходимости вручную отключи и подключи VPN. " +
                "Сама проверка Android не подтверждает восстановление VPN-трафика.",
            false,
        )
        return VpnRecoveryAdvice(
            "underlay_available", "Физическая сеть доступна",
            "Android подтвердил наличие физической сети. " +
                "Для проверки VPN-трафика открой сайт в браузере и проверь внешний IP отдельно.",
            false,
        )
    }

    /** elapsedRealtime starts anew at reboot; old timestamps are invalid. */
    fun ageSince(bootElapsedNowMs: Long, bootElapsedSinceMs: Long): Long? {
        if (bootElapsedSinceMs <= 0L || bootElapsedNowMs < bootElapsedSinceMs) return null
        val elapsed = bootElapsedNowMs - bootElapsedSinceMs
        return elapsed.takeIf { it <= MAX_TRACKED_MS }
    }
}
