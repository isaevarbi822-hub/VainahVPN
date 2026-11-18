package app.vainah.vpn

import java.io.ByteArrayInputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import org.junit.Assert.*
import org.junit.Test

/**
 * Entirely synthetic HTTPS server with a fake VLESS key.
 * No physical network, customer subscription or H1Cloud token is used.
 */
class SubscriptionRetryRecoveryTest {
    private val subscription = "https://other.example/sub?token=PRIVATE_TOKEN"
    private val fakeNode = "vless://00000000-0000-4000-8000-000000000001@" +
        "example.org:443?security=tls&type=tcp&sni=example.org#Turkey%20IP"

    private class Response(
        raw: String,
        private val code: Int = 200,
        private val payload: String = "",
        private val timeout: Boolean = false
    ) : HttpURLConnection(URL(raw)) {
        override fun connect() {}
        override fun disconnect() {}
        override fun usingProxy(): Boolean = false
        override fun getResponseCode(): Int {
            if (timeout) throw SocketTimeoutException(
                "private bearer token must not leak into UI"
            )
            return code
        }
        override fun getInputStream(): InputStream =
            ByteArrayInputStream(payload.toByteArray(Charsets.UTF_8))
    }

    @Test fun manualTimeoutRetriesOriginalAuthorizedHttpsLinkOnce() {
        var requests = 0
        var waited = 0L
        val nodes = SubscriptionServers.loadNodesWithRetry(
            subscription,
            retryOnTimeout = true,
            pause = { waited += it }
        ) { url ->
            requests++
            assertEquals(subscription, url)
            Response(url, payload = fakeNode, timeout = requests == 1)
        }
        assertEquals(2, requests)
        assertEquals(750L, waited)
        assertEquals(1, nodes.size)
        assertEquals("Turkey IP", nodes.single().label)
    }

    @Test fun backgroundLoadDoesNotRetryTransientTimeout() {
        var requests = 0
        val error = runCatching {
            SubscriptionServers.loadNodesWithRetry(subscription) { url ->
                requests++
                Response(url, timeout = true)
            }
        }.exceptionOrNull()
        assertTrue(error is SubscriptionRequestTimeout)
        assertEquals(1, requests)
        assertFalse(SubscriptionLoadFailure.explain(error!!).contains("PRIVATE_TOKEN"))
    }

    @Test fun manualRefreshNeverRetriesDeniedOrThrottledServer() {
        for (status in listOf(401, 403, 429, 500)) {
            var requests = 0
            val error = runCatching {
                SubscriptionServers.loadNodesWithRetry(
                    subscription, retryOnTimeout = true, pause = {}
                ) { url ->
                    requests++
                    Response(url, code = status)
                }
            }.exceptionOrNull()
            assertTrue(error is SubscriptionHttpStatus)
            assertEquals(status, (error as SubscriptionHttpStatus).status)
            assertEquals(1, requests)
        }
    }

    @Test fun cancelledProfileNeverTriggersSecondRequest() {
        var requests = 0
        var allowed = true
        val error = runCatching {
            SubscriptionServers.loadNodesWithRetry(
                subscription, retryOnTimeout = true,
                stillCurrent = { allowed },
                pause = { allowed = false }
            ) { url ->
                requests++
                Response(url, timeout = true)
            }
        }.exceptionOrNull()
        assertTrue(error is IllegalStateException)
        assertEquals(1, requests)
    }

    @Test fun secondTimeoutIsFinalFailureAndNeverLeaksLink() {
        var requests = 0
        val error = runCatching {
            SubscriptionServers.loadNodesWithRetry(
                subscription, retryOnTimeout = true, pause = {}
            ) { url ->
                requests++
                Response(url, timeout = true)
            }
        }.exceptionOrNull()
        assertTrue(error is SubscriptionRequestTimeout)
        assertEquals(2, requests)
        val safeMessage = SubscriptionLoadFailure.explain(error!!)
        assertFalse(safeMessage.contains("PRIVATE_TOKEN"))
        assertFalse(safeMessage.contains("other.example"))
    }

    @Test fun directVlessKeyNeverRepeatsOrCallsHttps() {
        val nodes = SubscriptionServers.loadNodesWithRetry(
            fakeNode, retryOnTimeout = true
        ) { throw AssertionError("Direct VLESS key must never call network") }
        assertEquals(1, nodes.size)
    }
}
