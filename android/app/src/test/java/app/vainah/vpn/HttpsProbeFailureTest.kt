package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class HttpsProbeFailureTest {
    @Test fun DNSFailureGetsDistinctCode() {
        assertEquals("dns_resolution_failed", HttpsProbeFailure.classify(
            java.net.UnknownHostException("private.example")))
    }

    @Test fun physicalRoutingFailuresAreDistinctFromDns() {
        assertEquals("https_no_route", HttpsProbeFailure.classify(
            java.net.NoRouteToHostException("private host")))
        assertEquals("https_connect_failed", HttpsProbeFailure.classify(
            java.net.ConnectException("private host")))
        assertEquals("https_socket_error", HttpsProbeFailure.classify(
            java.net.SocketException("private host")))
    }

    @Test fun SSLAndTimeoutHaveSpecificCodes() {
        assertEquals("tls_handshake_failed", HttpsProbeFailure.classify(
            javax.net.ssl.SSLException("private host")))
        assertEquals("https_timeout", HttpsProbeFailure.classify(
            java.net.SocketTimeoutException("private host")))
    }

    @Test fun unexpectedErrorsOnlyProduceConstantSafeCodes() {
        assertEquals("https_io_error", HttpsProbeFailure.classify(
            java.io.IOException("vless://never-export-a-secret")))
        assertEquals("https_network_binding_error", HttpsProbeFailure.classify(
            IllegalArgumentException("private host")))
        assertEquals("https_permission_error", HttpsProbeFailure.classify(
            SecurityException("private host")))
        assertEquals("https_probe_exception", HttpsProbeFailure.classify(
            IllegalStateException("secret token")))
    }
}
