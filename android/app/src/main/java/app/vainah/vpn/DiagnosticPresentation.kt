package app.vainah.vpn

/**
 * UI wording is derived from observed failures, not from a hardcoded HTTP 403
 * warning. A cached subscription is useful but does NOT prove current access.
 */
object DiagnosticPresentation {
    data class Subscription(
        val headline: String,
        val explanation: String,
        val warning: Boolean,
        val secondary: String
    )

    fun subscription(
        hasProfile: Boolean,
        cachedNodeCount: Int,
        fetching: Boolean,
        lastError: String?
    ): Subscription {
        if (!hasProfile) return Subscription(
            "Подписка не добавлена",
            "Добавь ссылку подписки или собственный VLESS-ключ.",
            false, "Нет сохранённого профиля"
        )
        if (fetching) return Subscription(
            "Обновляем подписку…",
            "Запрашиваем список серверов по HTTPS. Текущий VPN-сеанс не переключается.",
            false, "Проверка выполняется"
        )
        if (!lastError.isNullOrBlank()) {
            val is403 = Regex("(^|[^0-9])403([^0-9]|$)").containsMatchIn(lastError)
            return if (is403) Subscription(
                "Доступ к обновлению ограничен · HTTP 403",
                "Сервер отклонил запрос приложения. Это не означает, " +
                    "что VPN-туннель перестал работать или подписка закончилась.",
                true, if (cachedNodeCount > 0)
                    "Кэш: ${cachedNodeCount} серверов — актуальность не проверена"
                else "Обновление недоступно"
            ) else Subscription(
                "Не удалось обновить подписку",
                lastError.take(220),
                true, if (cachedNodeCount > 0)
                    "Сохранено: ${cachedNodeCount} серверов"
                else "Нет доступного списка серверов"
            )
        }
        if (cachedNodeCount > 0) return Subscription(
            "Список серверов загружен",
            "В приложении есть ${cachedNodeCount} конфигураций. " +
                "Работа VPN и внешний IP проверяются отдельно.",
            false, "Локально: ${cachedNodeCount} серверов"
        )
        return Subscription(
            "Серверы пока не загружены",
            "Обнови подписку по HTTPS или проверь сохранённый профиль.",
            false, "Нет загруженных конфигураций"
        )
    }

    fun tunnelHeadline(phase: String, serviceRunning: Boolean): String =
        when {
            !serviceRunning || phase == VpnConnectionState.OFF ->
                "VPN сейчас не запущен"
            phase == VpnConnectionState.STARTING -> "VPN подключается"
            phase == VpnConnectionState.FAILED -> "VPN: ошибка соединения"
            phase == VpnConnectionState.ONLINE ||
                phase == VpnConnectionState.TUN_READY ->
                "Туннель создан · внешний IP не проверен"
            else -> "Статус VPN ещё не подтверждён"
        }
}
