package app.vainah.vpn

/**
 * Explains a physical TCP reachability check without revealing the VLESS
 * endpoint, SNI, public key, UUID or subscription bearer token.
 * TCP reachability does not verify a VLESS/REALITY/TLS handshake, data
 * transfer, or the throughput available from a VPN server.
 */
internal object ServerHealthPresentation {
    data class Result(val summary: String, val explanation: String)

    fun assess(
        details: SubscriptionNodeSupport.Details?,
        observation: ServerTcpObservation?
    ): Result {
        if (details == null) return Result(
            "Профиль не распознан",
            "Проверь транспорт и формат узла в подписке H1Cloud. Не передавай VPN-ключ."
        )
        if (!details.connectable) return Result(
            "Транспорт недоступен в этой APK",
            "Узел имеет тип ${details.subtitle}, но текущий движок не сможет его запустить. " +
                "Не подменяй транспорт вручную."
        )
        if (observation == null || observation.attempts != ServerTcpSelector.ATTEMPTS_PER_NODE)
            return Result(
                "TCP ещё не проверен",
                "Можно проверить только доступность входного порта. " +
                    "Это не измерение VPN-скорости или работы REALITY."
            )
        val successes = observation.successes.coerceAtMost(observation.attempts)
        val measured = if (successes >= 2 && observation.samplesMs.size <= observation.attempts)
            observation.medianMs else null
        val summary = if (measured != null)
            "TCP ${successes}/${observation.attempts} · ${measured} мс"
        else "TCP ${successes}/${observation.attempts} · нет надёжного замера"
        val explanation = if (successes == 0)
            "Входной TCP-порт не ответил. Проверь сеть и доступность этого узла в H1Cloud."
        else "Проверка TCP не подтверждает TLS/REALITY, VPN-туннель или скорость. " +
            "При сбое подключения сравни параметры транспорта с H1Cloud."
        return Result(summary, explanation)
    }
}
