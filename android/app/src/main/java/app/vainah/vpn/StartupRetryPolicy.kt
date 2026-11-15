package app.vainah.vpn

/**
 * A temporary physical-network failure before Android TUN establishment.
 * Never include the hostname, server IP, UUID or bearer subscription URL.
 */
class VpnStartupNetworkException(val reason: Reason) :
    IllegalStateException("Physical network preflight unavailable: ${reason.name.lowercase()}") {
    enum class Reason { NO_UNDERLAY, ENDPOINT_UNREACHABLE }
}

/**
 * One bounded retry for transient DNS/TCP/wifi-to-cellular instability.
 * Configuration errors and expired/rejected subscriptions are NEVER retried.
 * The caller's session generation is checked before each attempt and delay.
 */
object StartupRetryPolicy {
    const val MAX_ATTEMPTS = 2
    const val RETRY_DELAY_MS = 900L

    fun retryable(error: Throwable): Boolean = error is VpnStartupNetworkException

    fun <T> execute(
        stillRequested: () -> Boolean,
        connect: () -> T,
        delay: (Long) -> Unit = { Thread.sleep(it) }
    ): T {
        var attempt = 0
        while (true) {
            if (!stillRequested()) throw IllegalStateException("VPN connection cancelled")
            attempt++
            try {
                return connect()
            } catch (failure: Exception) {
                if (!retryable(failure) || attempt >= MAX_ATTEMPTS || !stillRequested())
                    throw failure
                delay(RETRY_DELAY_MS)
            }
        }
    }
}
