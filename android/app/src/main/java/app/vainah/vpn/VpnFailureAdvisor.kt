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
            "После неожиданной остановки возможны до двух попыток автовосстановления. " +
                "Если они не помогли, проверь Wi-Fi или LTE и подключись вручную."
        ),
        "resolving_h1cloud_before_vpn" to VpnFailureAdvice(
            "upstream_unreachable", "Не удалось проверить входной VPN-сервер",
            "TCP-порт может отвечать, даже если VPN-протокол не работает. " +
                "Проверь другой сервер и отправь обезличенный отчёт диагностики."
        ),
        "initializing_libbox_setup" to VpnFailureAdvice(
            "libbox_initialization", "Ошибка инициализации libbox",
            "Закрой другие VPN-приложения и попробуй повторно. При повторении отправь обезличенный отчёт."
        ),
        "validating_libbox_config" to VpnFailureAdvice(
            "config_validation", "Конфигурация не прошла проверку",
            "Подписка может быть действующей: встроенный libbox не принял " +
                "параметры этого сервера (возможна несовместимость XHTTP/REALITY). " +
                "Повторное обновление подписки само по себе это не исправит. " +
                "Выбери другой сервер и отправь обезличенный отчёт."
        ),
        "validating_selected_profile" to VpnFailureAdvice(
            "profile_invalid", "Параметры сервера не поддерживаются",
            "Этот профиль не удалось преобразовать в конфигурацию VPN. " +
                "Подписка может быть актуальной. Попробуй другой сервер " +
                "и отправь обезличенный отчёт."
        ),
        "subscription_storage_unavailable" to VpnFailureAdvice(
            "subscription_storage", "Сохранённая подписка недоступна",
            "Приложение не может прочитать зашифрованную ссылку на устройстве. " +
                "Проверь подписку в кабинете; не оплачивай повторно."
        ),
        "engine_unavailable" to VpnFailureAdvice(
            "engine_missing", "VPN-движок отсутствует в этой сборке",
            "Установи тестовую сборку VainahVPN с libbox. " +
                "Повторное обновление подписки не поможет."
        ),
        "loading_libbox_service" to VpnFailureAdvice(
            "transport_startup", "VPN-транспорт не запустился",
            "Встроенный движок не смог запустить выбранный сервер. " +
                "Попробуй другой сервер; для проверки XHTTP/REALITY " +
                "отправь обезличенный отчёт."
        ),
        "starting_libbox_command_server" to VpnFailureAdvice(
            "transport_startup", "VPN-транспорт не запустился",
            "Встроенный движок не смог запустить выбранный сервер. " +
                "Попробуй другой сервер и отправь обезличенный отчёт."
        ),
        "opening_android_tun" to VpnFailureAdvice(
            "tun_establishment", "Android не открыл VPN-туннель",
            "Проверь разрешение VPN и настройки блокировки подключений без VPN в системе."
        ),
        "verifying_android_tun" to VpnFailureAdvice(
            "tun_establishment", "Туннель libbox не подтверждён",
            "Проверь разрешение VPN и отсутствие другого активного VPN-приложения."
        ),
        "vpn_https_probe_timeout" to VpnFailureAdvice(
            "egress_inconclusive", "Проверка HTTPS не ответила",
            "Приложение не получило результат собственной HTTPS-пробы вовремя. " +
                "Это не означает, что интернет в браузере не работает. " +
                "Проверь браузер, IP и DNS отдельно."
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
