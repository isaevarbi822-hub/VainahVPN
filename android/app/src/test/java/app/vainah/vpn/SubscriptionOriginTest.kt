package app.vainah.vpn

import java.io.ByteArrayInputStream
import java.net.HttpURLConnection
import java.net.URL
import org.junit.Assert.*
import org.junit.Test

class SubscriptionOriginTest {
    private class Denied(url: String) : HttpURLConnection(URL(url)) {
        override fun connect() {}
        override fun disconnect() {}
        override fun usingProxy() = false
        override fun getResponseCode() = 403
        override fun getErrorStream() =
            ByteArrayInputStream("Forbidden".toByteArray(Charsets.UTF_8))
    }

    @Test fun correctlyIdentifiesOldNetlifyAndPythonRenderWithoutRevealingUrl() {
        val sources = listOf(
            "https://vainahvpnbot0.netlify.app/.netlify/functions/sub?token=PRIVATE" to
                SubscriptionOrigin.Kind.LEGACY_NETLIFY,
            "https://vainahvpn-python-preview.onrender.com/sub?token=PRIVATE" to
                SubscriptionOrigin.Kind.PYTHON_RENDER,
            "https://my.h1cloud.net/sub?token=PRIVATE" to
                SubscriptionOrigin.Kind.H1CLOUD,
            "https://unrelated.example/sub?token=PRIVATE" to
                SubscriptionOrigin.Kind.OTHER_HTTPS
        )
        for ((url, source) in sources) {
            assertEquals(source, SubscriptionOrigin.fromLink(url))
            val label = SubscriptionOrigin.label(source)
            assertFalse(label.contains("PRIVATE"))
            assertFalse(label.contains("/sub"))
        }
    }

    @Test fun http403SaysWhichTypeOfServerActuallyResponded() {
        val url = "https://vainahvpn-python-preview.onrender.com/s?token=PRIVATE"
        val error = runCatching {
            SubscriptionServers.loadNodesWithConnection(url) { Denied(it) }
        }.exceptionOrNull()
        assertTrue(error is SubscriptionHttpStatus)
        val response = error as SubscriptionHttpStatus
        assertEquals(403, response.status)
        assertEquals(SubscriptionOrigin.Kind.PYTHON_RENDER, response.source)
        val display = SubscriptionLoadFailure.explain(response)
        assertTrue(display.contains("Python/Render"))
        assertFalse(display.contains("PRIVATE"))
        assertFalse(display.contains("onrender.com"))
    }

    @Test fun privateLinkNeverExposedEvenWhenDeniedByUnknownHost() {
        val raw = "https://secret-vpn.example/sub?token=PRIVATE"
        val error = runCatching {
            SubscriptionServers.loadNodesWithConnection(raw) { Denied(it) }
        }.exceptionOrNull()
        assertTrue(error is SubscriptionHttpStatus)
        assertEquals(SubscriptionOrigin.Kind.OTHER_HTTPS,
            (error as SubscriptionHttpStatus).source)
        val text = SubscriptionLoadFailure.explain(error)
        assertFalse(text.contains("secret-vpn.example"))
        assertFalse(text.contains("PRIVATE"))
    }
}
