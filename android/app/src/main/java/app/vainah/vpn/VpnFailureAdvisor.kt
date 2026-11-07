package app.vainah.vpn

/**
 * Codes are derived ONLY from known internal engine stages.
 * Native exception messages (which may contain UUIDs/hostnames) are never
 * used, saved, exported or displayed.
 */
data class VpnFailureAdvice(
    val code: String,
    val title: String,
    val action: String,
)

object VpnFailureAdvisor {
    private val known = mapOf(
        "native_engine_stopped" to VpnFailureAdvice(
            "engine_stopped", "VPN-движок остановился",
            "Проверь соединение и открой приложение. Повторное подключение выполняется вручную."
        ),
        "resolving_h1cloud_before_vpn" to VpnFailureAdvice(
            "upstream_unreachable", "Не удалось проверить входной VPN-сервер",
            "Проверь Wi-Fi/4G без VPN, обнови подписку и попробуй другую локацию."
        ),
        "initializing_libbox_setup" to VpnFailureAdvice(
            "libbox_initialization", "Ошибка инициализации libbox",
            "Закрой другие VPN-приложения и попробуй повторно. При повторении отправь обезличенный отчёт."
        ),
        "validating_libbox_config" to VpnFailureAdvice(
            "config_validation", "Конфигурация не прошла проверку",
            "Обнови подписку из личного кабинета. Не публикуй VLESS-ключ в поддержке."
        ),
        "opening_android_tun" to VpnFailureAdvice(
            "tun_establishment", "Android не открыл VPN-туннель",
            "Проверь разрешение VPN и настройки блокировки подключений без VPN в системе."
        ),
        "verifying_android_tun" to VpnFailureAdvice(
            "tun_establishment", "Туннель libbox не подтверждён",
            "Проверь разрешение VPN и отсутствие другого активного VPN-приложения."
        ),
        "checking_vpn_https_egress" to VpnFailureAdvice(
            "egress_inconclusive", "Проверка интернета не завершена",
            "Открой сайт в браузере и отдельно проверь внешний IP. Проба приложения не подтверждает работу VPN в других приложениях."
        ),
        "starting_libbox_native_engine" to VpnFailureAdvice(
            "libbox_startup", "VPN-движок не запустился",
            "Проверь разрешение VPN, затем попробуй вручную подключиться. При повторении отправь обезличенный отчёт."
        ),
    )
    private val default = VpnFailureAdvice(
        "engine_error", "Сбой VPN-службы",
        "Проверь сеть, разрешение VPN и состояние подписки. Не оплачивай подписку повторно из-за этой ошибки."
    )
    private val allowed = (known.values.map { it.code } + default.code).toSet()

    fun fromStage(stage: String?): VpnFailureAdvice =
        known[stage] ?: default

    fun sanitizedCode(value: String?): String =
        value?.takeIf { it in allowed } ?: "unknown"

    fun fromCode(value: String?): VpnFailureAdvice =
        known.values.firstOrNull { it.code == sanitizedCode(value) } ?: default
}
