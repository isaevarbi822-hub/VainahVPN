package app.vainah.vpn

/**
 * Small in-memory ring of *measured* libbox traffic readings.
 * Never persists browsing history, IP addresses, domain names or profiles.
 * Unknown counters are represented by an empty history, never fake zeroes.
 */
class TrafficTimeline(private val capacity: Int = 42) {
    init { require(capacity in 2..240) }

    data class Point(
        val elapsedMs: Long,
        val downBytesPerSecond: Long,
        val upBytesPerSecond: Long
    ) {
        val combined: Long get() =
            (downBytesPerSecond + upBytesPerSecond).coerceAtLeast(0L)
    }

    private val points = ArrayDeque<Point>()

    fun clear() = points.clear()

    fun size(): Int = points.size

    fun record(elapsedMs: Long, down: Long, up: Long): Boolean {
        if (elapsedMs < 0L || down < 0 || up < 0) return false
        val previous = points.lastOrNull()
        // Coalesce duplicate ticks; reject clocks going backwards.
        if (previous != null && elapsedMs <= previous.elapsedMs) return false
        if (previous != null && elapsedMs - previous.elapsedMs > 15_000L)
            points.clear() // A gap means the chart is no longer live.
        points.addLast(Point(elapsedMs, down, up))
        while (points.size > capacity) points.removeFirst()
        return true
    }

    fun snapshot(): List<Point> = points.toList()

    fun peakBytesPerSecond(): Long = points.maxOfOrNull { it.combined } ?: 0L

    fun last(): Point? = points.lastOrNull()
}

/** Explicit connectivity statuses: a TUN alone does not verify external egress. */
object ConnectionQuality {
    enum class Stage { OFF, STARTING, TUN_CREATED, FAILURE }

    fun stage(phase: String, serviceRunning: Boolean): Stage = when {
        phase == VpnConnectionState.FAILED -> Stage.FAILURE
        !serviceRunning || phase == VpnConnectionState.OFF -> Stage.OFF
        phase == VpnConnectionState.STARTING -> Stage.STARTING
        phase == VpnConnectionState.TUN_READY ||
            phase == VpnConnectionState.ONLINE -> Stage.TUN_CREATED
        else -> Stage.OFF
    }

    fun text(stage: Stage): String = when(stage) {
        Stage.OFF -> "VPN выключен"
        Stage.STARTING -> "Подключение…"
        Stage.TUN_CREATED -> "Туннель запущен · внешний IP не проверен"
        Stage.FAILURE -> "Ошибка VPN · смотри диагностику"
    }
}
