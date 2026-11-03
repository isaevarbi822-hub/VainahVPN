package app.vainah.vpn

import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import org.junit.Assert.*
import org.junit.Test

class SubscriptionTimeoutTest {
    private class Timeout(url: String) : HttpURLConnection(URL(url)) {
        override fun disconnect() {}
        override fun connect() {}
        override fun usingProxy() = false
        override fun getResponseCode(): Int =
            throw SocketTimeoutException("Sensitive token=SECRET_VALUE is never shown")
    }

    @Test fun pythonPreviewHasLongReadTimeoutWithoutDisablingHttpsChecks() {
        val connection = Timeout("https://vainahvpn-python-preview.onrender.com/sub?token=SECRET")
        SubscriptionServers.configureConnection(connection)
        assertEquals(85000, connection.readTimeout)
        assertEquals(12000, connection.connectTimeout)
        assertFalse(connection.instanceFollowRedirects)
    }

    @Test fun h1cloudAndLegacyDomainsKeepOrdinaryTimeouts() {
        for (url in listOf(
            "https://my.h1cloud.net/sub?token=SECRET",
            "https://vainahvpnbot0.netlify.app/sub?token=SECRET",
            "https://unknown.example/sub?token=SECRET"
        )) {
            val connection = Timeout(url)
            SubscriptionServers.configureConnection(connection)
            assertEquals(12000, connection.readTimeout)
            assertEquals(8000, connection.connectTimeout)
        }
    }

    @Test fun timeoutDiagnosticIdentifiesPythonWithoutExposingSecret() {
        val raw = "https://vainahvpn-python-preview.onrender.com/sub?token=SECRET_VALUE"
        val error = runCatching {
            SubscriptionServers.loadNodesWithConnection(raw) { Timeout(it) }
        }.exceptionOrNull()
        assertTrue(error is SubscriptionRequestTimeout)
        val msg = SubscriptionLoadFailure.explain(error!!)
        assertTrue(msg.contains("Python/Render"))
        assertTrue(msg.contains("85 секунд"))
        assertFalse(msg.contains("SECRET_VALUE"))
        assertFalse(msg.contains("onrender.com"))
    }

    @Test fun timeoutDiagnosticDoesNotCallEveryServerH1Cloud() {
        val raw = "https://vpn.example/sub?token=SECRET_VALUE"
        val error = runCatching {
            SubscriptionServers.loadNodesWithConnection(raw) { Timeout(it) }
        }.exceptionOrNull()
        assertTrue(error is SubscriptionRequestTimeout)
        val msg = SubscriptionLoadFailure.explain(error!!)
        assertTrue(msg.contains("другой HTTPS-сервер"))
        assertFalse(msg.contains("H1Cloud"))
        assertFalse(msg.contains("SECRET_VALUE"))
    }
}
