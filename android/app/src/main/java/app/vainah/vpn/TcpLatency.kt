package app.vainah.vpn

/** Median of successful *physical TCP connect* latencies in milliseconds.
 * Never represents a REALITY/TLS handshake latency or VPN tunnel ping.
 */
object TcpLatency {
    fun median(samples: List<Int>): Int? {
        val sorted = samples.filter { it in 0..60000 }.sorted()
        if (sorted.isEmpty()) return null
        val midpoint = sorted.size / 2
        return if (sorted.size % 2 == 1) sorted[midpoint]
        else (sorted[midpoint - 1].toLong() + sorted[midpoint].toLong())
            .div(2).toInt()
    }
}
