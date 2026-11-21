package app.vainah.vpn

import java.net.InetSocketAddress
import java.net.Socket
import java.net.URI
import java.util.concurrent.TimeUnit

/**
 * Physical TCP port connect measurements for VLESS entry points.
 *
 * NOT VPN tunnel latency, bandwidth, REALITY/TLS verification, server load
 * or proof that traffic will successfully traverse the remote VPN.
 * Never prints or saves a subscription URL, credentials or destination host.
 * All socket work must be called from a background thread.
 */
data class ServerTcpObservation(
    val index: Int,
    val attempts: Int,
    val samplesMs: List<Int>,
) {
    val medianMs: Int? get() = TcpLatency.median(samplesMs)
    val successes: Int get() = samplesMs.count { it in 0..60000 }
}

object ServerTcpSelector {
    const val MAX_PROBED_NODES = 8
    const val ATTEMPTS_PER_NODE = 3
    const val CONNECT_TIMEOUT_MS = 1200

    /**
     * At least two measured connections are needed before auto-selecting.
     * Ties use success count, then subscription order; no estimated pings.
     */
    fun best(observations: List<ServerTcpObservation>): Int? =
        observations.filter {
            it.index >= 0 && it.attempts == ATTEMPTS_PER_NODE &&
                it.successes >= 2 && it.medianMs != null
        }.minWithOrNull(compareBy<ServerTcpObservation>(
            { it.medianMs ?: Int.MAX_VALUE },
            { -it.successes },
            { it.index },
        ))?.index

    fun endpoint(node: VainahNode): Pair<String, Int>? {
        return runCatching {
            val uri = URI(node.uri)
            if (!uri.scheme.equals("vless", ignoreCase = false) ||
                uri.host.isNullOrBlank() || uri.port !in 1..65535 ||
                uri.rawUserInfo.isNullOrBlank() || uri.host!!.length > 253) {
                null
            } else {
                // Reuse our existing REALITY/TCP validation. Do not send URL
                // or UUID anywhere, only open the configured host:port.
                VlessRealityConfig.outbound(node.uri)
                uri.host!! to uri.port
            }
        }.getOrNull()
    }
}

object ServerTcpMeasurement {
    fun sample(node: VainahNode): ServerTcpObservation {
        val endpoint = ServerTcpSelector.endpoint(node)
            ?: return ServerTcpObservation(-1, ServerTcpSelector.ATTEMPTS_PER_NODE, emptyList())
        val results = ArrayList<Int>(ServerTcpSelector.ATTEMPTS_PER_NODE)
        repeat(ServerTcpSelector.ATTEMPTS_PER_NODE) {
            try {
                Socket().use { socket ->
                    val started = System.nanoTime()
                    socket.connect(
                        InetSocketAddress(endpoint.first, endpoint.second),
                        ServerTcpSelector.CONNECT_TIMEOUT_MS,
                    )
                    val elapsed = TimeUnit.NANOSECONDS.toMillis(
                        System.nanoTime() - started
                    ).coerceIn(0, 60000)
                    results.add(elapsed.toInt())
                }
            } catch (_: Exception) {
                // A timeout or rejected TCP connection is NOT a zero-ms ping.
                // Exceptions may contain server addresses; do not log them.
            }
        }
        return ServerTcpObservation(-1, ServerTcpSelector.ATTEMPTS_PER_NODE, results)
    }
}
