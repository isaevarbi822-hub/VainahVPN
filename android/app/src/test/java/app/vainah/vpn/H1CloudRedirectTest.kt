package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL

class H1CloudRedirectTest {
    private val testVless = "vless://12345678-1234-1234-1234-123456789abc@node.example.com:443" +
        "?security=reality&type=tcp&sni=example.com&pbk=AbCdEfGhIjKlMnOpQrStUvWxYz012345#Germany"

    private class Response(
        url: String,
        private val status: Int,
        private val redirect: String? = null,
        private val payload: String = ""
    ) : HttpURLConnection(URL(url)) {
        var disconnected = false
        override fun getResponseCode(): Int = status
        override fun getHeaderField(name: String?): String? =
            if (name.equals("location", ignoreCase = true)) redirect else null
        override fun getInputStream(): InputStream = ByteArrayInputStream(payload.toByteArray(Charsets.UTF_8))
        override fun disconnect() { disconnected = true }
        override fun usingProxy() = false
        override fun connect() {}
    }

    @Test fun followsSameOriginHttpsRedirectThenParsesServer() {
        val first = "https://panel.example.com/sub?token=PRIVATE_TOKEN"
        val second = "https://panel.example.com/subscribe?token=OTHER_PRIVATE_TOKEN"
        val seen = mutableListOf<String>()
        val responses = mutableListOf<Response>()
        val nodes = SubscriptionServers.loadNodesWithConnection(first) { address ->
            seen.add(address)
            val response = if (seen.size == 1) Response(address, 302, "/subscribe?token=OTHER_PRIVATE_TOKEN")
                else Response(address, 200, payload = testVless)
            responses.add(response)
            response
        }
        assertEquals(listOf(first, second), seen)
        assertEquals(1, nodes.size)
        assertEquals("🇩🇪 Германия", nodes.first().label)
        assertTrue(responses.all { it.disconnected })
    }

    @Test fun rejectsCrossOriginAndHttpDowngradeBeforeAnySecondRequest() {
        for (redirect in listOf(
            "https://bad.example.com/?token=PRIVATE_TOKEN",
            "http://panel.example.com/sub",
            "https://user@panel.example.com/sub",
            "https://panel.example.com/sub#fragment"
        )) {
            var requests = 0
            val error = runCatching {
                SubscriptionServers.loadNodesWithConnection(
                    "https://panel.example.com/sub?token=PRIVATE_TOKEN"
                ) { address ->
                    requests++
                    Response(address, 301, redirect)
                }
            }.exceptionOrNull()
            assertTrue(error is SubscriptionHttpStatus)
            assertEquals(1, requests)
        }
    }

    @Test fun cannotFollowMoreThanTwoRedirects() {
        var requests = 0
        val error = runCatching {
            SubscriptionServers.loadNodesWithConnection("https://panel.example.com/start") { address ->
                requests++
                Response(address, 302, "/next?hop=$requests")
            }
        }.exceptionOrNull()
        assertTrue(error is SubscriptionHttpStatus)
        assertEquals(3, requests)
    }

    @Test fun http403NeverSwitchesToAnotherUrlOrChangesTLSSettings() {
        var requests = 0
        val error = runCatching {
            SubscriptionServers.loadNodesWithConnection("https://panel.example.com/sub") { url ->
                requests++
                Response(url, 403)
            }
        }.exceptionOrNull()
        assertEquals(1, requests)
        assertTrue(error is SubscriptionHttpStatus)
        assertEquals(403, (error as SubscriptionHttpStatus).status)
    }
}
