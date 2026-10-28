package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test
import java.net.ConnectException
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.net.URL
import javax.net.ssl.SSLException

class SubscriptionLoadFailureTest {
    @Test fun expiredOrInvalidSubscriptionIsNotInferredFromHttp403() {
        val detail = SubscriptionLoadFailure.explain(SubscriptionHttpStatus(403))
        assertTrue(detail.contains("403"))
        assertTrue(detail.contains("другом VPN-клиенте"))
        assertFalse(detail.contains("продлить"))
        assertFalse(detail.contains("неправильн"))
    }

    @Test fun distinguishesHttpCodesAndNetworkErrorsWithoutSecrets() {
        val data = listOf(
            SubscriptionHttpStatus(401) to "401",
            SubscriptionHttpStatus(404) to "404",
            SubscriptionHttpStatus(429) to "429",
            SubscriptionHttpStatus(503) to "503",
            UnknownHostException("host PRIVATE_TOKEN") to "DNS",
            SocketTimeoutException("secret URL") to "Тайм-аут",
            ConnectException("secret URL") to "HTTPS",
            SSLException("secret URL") to "TLS"
        )
        for ((error, expected) in data) {
            val message = SubscriptionLoadFailure.explain(error)
            assertTrue(message, message.contains(expected))
            assertFalse(message, message.contains("PRIVATE_TOKEN"))
            assertFalse(message, message.contains("secret URL"))
        }
    }

    @Test fun requestUsesOwnAndroidClientIdentityWithoutChangingTlsPolicy() {
        val connection = object : HttpURLConnection(URL("https://test.example/")) {
            override fun disconnect() {}
            override fun usingProxy() = false
            override fun connect() {}
        }
        SubscriptionServers.configureConnection(connection)
        assertTrue(connection.getRequestProperty("User-Agent").startsWith("VainahVPN-Android/"))
        assertTrue(connection.getRequestProperty("User-Agent").contains(BuildConfig.VERSION_NAME))
        assertTrue(connection.getRequestProperty("Accept").contains("text/plain"))
        assertTrue(connection.getRequestProperty("Accept").contains("application/json"))
        assertTrue(connection.getRequestProperty("Accept").contains("application/octet-stream"))
        assertEquals("no-cache", connection.getRequestProperty("Cache-Control"))
        assertFalse(connection.instanceFollowRedirects)
        assertFalse(connection.useCaches)
        assertEquals(8000, connection.connectTimeout)
    }
}
