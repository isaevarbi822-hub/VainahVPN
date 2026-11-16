package app.vainah.vpn

/**
 * A physical TCP socket test only. Never interprets an open TCP port as a
 * successful VLESS/REALITY handshake, working VPN traffic or a speed test.
 */
object SelectedServerTcpAdvice {
    fun summary(observation: ServerTcpObservation): String = when {
        observation.attempts != ServerTcpSelector.ATTEMPTS_PER_NODE ||
            observation.samplesMs.size > observation.attempts ->
            "Замер недостоверен. Повтори проверку."
        observation.successes >= 2 ->
            "TCP-вход доступен: " + observation.medianMs + " мс. " +
                "VLESS, REALITY, внешний IP и скорость ещё не проверены."
        observation.successes == 1 ->
            "TCP-вход отвечает нестабильно (1 из 3). " +
                "Проверь доступность сервера и его порт в H1Cloud."
        else ->
            "TCP-вход не отвечает (0 из 3). " +
                "Проверь адрес, порт и доступность этого узла в H1Cloud."
    }
}
