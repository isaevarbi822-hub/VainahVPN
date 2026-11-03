package app.vainah.vpn

import java.io.ByteArrayInputStream
import java.net.HttpURLConnection
import java.net.URL
import org.junit.Assert.*
import org.junit.Test

class SubscriptionUserAgentTest {
    private class Request(url: String) : HttpURLConnection(URL(url)) {
        override fun connect() {}
        override fun disconnect() {}
        override fun usingProxy() = false
        override fun getResponseCode(): Int = 403
        override fun getErrorStream() =
            ByteArrayInputStream("Forbidden".toByteArray())
    }

    @Test fun remainsIdentifiablyVainahByDefault() {
        val req = Request("https://example.org/sub?token=SECRET")
        SubscriptionServers.configureConnection(req)
        assertEquals("VainahVPN-Android/" + BuildConfig.VERSION_NAME,
            req.getRequestProperty("User-Agent"))
        assertNull(req.getRequestProperty("X-HWID"))
    }

    @Test fun onlyExplicitApprovedUserAgentIsTransmitted() {
        val chosen = "AllowedClient/4.8.0/Android/123456"
        val req = Request("https://example.org/sub")
        SubscriptionServers.configureConnection(req, emptyMap(), chosen)
        assertEquals(chosen, req.getRequestProperty("User-Agent"))
        assertFalse(req.instanceFollowRedirects)
        assertEquals(12000, req.readTimeout)
    }

    @Test fun identityHeadersAndUserAgentCanBeConfiguredIndependently() {
        val headers = SubscriptionHwidHeaders.build(
            "b23d22bc-6188-4ffd-8dce-f7c5ee9ca10a", "16", "SM-S938B")
        val req = Request("https://example.org/sub")
        SubscriptionServers.configureConnection(req, headers, "AllowedClient/4.8.0")
        assertEquals("AllowedClient/4.8.0",
            req.getRequestProperty("User-Agent"))
        assertEquals(headers["X-HWID"], req.getRequestProperty("X-HWID"))
    }

    @Test fun preventsHeaderInjectionAndAccidentalCredentialSending() {
        for (ua in listOf(
            "x\r\nAuthorization: Bearer SECRET",
            "https://panel.example.com/sub?token=SECRET",
            "Authorization: Bearer SECRET",
            "token=SECRET",
            "a".repeat(181),
            "abc"
        )) {
            assertNull(SubscriptionUserAgent.validate(ua))
            assertEquals("VainahVPN-Android/0.5.14",
                SubscriptionUserAgent.effective(ua, "0.5.14"))
        }
        assertEquals("AllowedClient/4.8.0",
            SubscriptionUserAgent.validate(" AllowedClient/4.8.0 "))
    }

    @Test fun errorNeverExposesUserAgentOrSubscriptionToken() {
        val secretUrl = "https://example.org/sub?token=PRIVATE"
        val customUa = "AllowedClient/4.8.0/device-id"
        val error = runCatching {
            SubscriptionServers.loadNodesWithConnection(
                secretUrl, emptyMap(), customUa
            ) { url ->
                val req = Request(url)
                req
            }
        }.exceptionOrNull()!!
        assertTrue(error is SubscriptionHttpStatus)
        assertEquals(403, (error as SubscriptionHttpStatus).status)
        val msg = SubscriptionLoadFailure.explain(error)
        assertFalse(msg.contains(customUa))
        assertFalse(msg.contains("PRIVATE"))
    }
}
