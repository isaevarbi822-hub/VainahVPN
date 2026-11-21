package app.vainah.vpn

/**
 * Safe, credential-free HTTPS probe failure classifications.
 * Do not store Throwable.message: it may contain a hostname, IP or
 * personal subscription URL. Android VPN owner-UID probes are advisory.
 */
object HttpsProbeFailure {
    fun classify(error: Throwable): String = when (error) {
        is java.net.UnknownHostException -> "dns_resolution_failed"
        is java.net.NoRouteToHostException -> "https_no_route"
        is java.net.SocketTimeoutException -> "https_timeout"
        is java.net.ConnectException -> "https_connect_failed"
        is javax.net.ssl.SSLException -> "tls_handshake_failed"
        is java.net.SocketException -> "https_socket_error"
        is java.io.InterruptedIOException -> "https_io_timeout"
        is java.io.IOException -> "https_io_error"
        is SecurityException -> "https_permission_error"
        is IllegalArgumentException -> "https_network_binding_error"
        else -> "https_probe_exception"
    }
}
