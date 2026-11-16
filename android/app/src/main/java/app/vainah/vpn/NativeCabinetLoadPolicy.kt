package app.vainah.vpn

/**
 * One shared timeout for all optional read-only native account resources.
 * Uses a monotonic clock; the limit is for the entire refresh, not each
 * endpoint. The underlying HTTP requests retain their own short timeouts.
 */
internal object NativeCabinetLoadPolicy {
    const val TOTAL_BUDGET_NANOS = 20_000_000_000L

    fun deadlineNanos(startNanos: Long): Long =
        startNanos + TOTAL_BUDGET_NANOS

    fun remainingNanos(nowNanos: Long, deadlineNanos: Long): Long =
        (deadlineNanos - nowNanos).coerceAtLeast(0L)
}
