package app.vainah.vpn

import java.io.ByteArrayInputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import org.junit.Assert.*
import org.junit.Test

class Subscription403DiagnosticsTest {
    private class Denial(
        url: String, private val text: String, private val edge: Boolean = false
    ) : HttpURLConnection(URL(url)) {
        override fun disconnect() {}
        override fun usingProxy() = false
        override fun connect() {}
        override fun getResponseCode(): Int = 403
        override fun getErrorStream(): InputStream =
            ByteArrayInputStream(text.toByteArray(Charsets.UTF_8))
        override fun getHeaderField(name: String?): String? =
            if (edge && name.equals("cf-ray", ignoreCase = true)) "TEST" else null
    }

    @Test fun categorizesProviderDeniedResponseWithoutDisplayingRawBody() {
        val secret = "https://panel.example.com/sub?token=PRIVATE_SECRET"
        val response = Denial(secret,
            "{\"error\":\"hwid required\",\"url\":\"$secret\"}")
        val result = runCatching {
            SubscriptionServers.loadNodesWithConnection(secret) { response }
        }.exceptionOrNull()
        assertTrue(result is SubscriptionHttpStatus)
        val error = result as SubscriptionHttpStatus
        assertEquals(403, error.status)
        assertEquals(SubscriptionDenial.Kind.HWID_REQUIRED, error.category)
        val safe = SubscriptionLoadFailure.explain(error)
        assertTrue(safe.contains("HWID"))
        assertFalse(safe.contains("PRIVATE_SECRET"))
        assertFalse(safe.contains("panel.example.com"))
    }

    @Test fun detectsEdgeChallengeAndDeviceLimitAndUnknown() {
        assertEquals(SubscriptionDenial.Kind.EDGE_CHALLENGE,
            SubscriptionDenial.fromResponse(Denial(
                "https://panel.example.com/sub", "anything", true)))
        assertEquals(SubscriptionDenial.Kind.DEVICE_LIMIT,
            SubscriptionDenial.classify("Too many devices on this subscription"))
        assertEquals(SubscriptionDenial.Kind.CLIENT_POLICY,
            SubscriptionDenial.classify("Unsupported User-Agent"))
        assertEquals(SubscriptionDenial.Kind.UNKNOWN,
            SubscriptionDenial.classify("token=PRIVATE_SECRET secret HOST\n" +
                "x".repeat(6000)))
    }

    @Test fun comparisonOperatesOnExactNormalizedLinksAndNeverDisplaysSecrets() {
        val saved = "https://panel.example.com/sub?token=PRIVATE_A"
        assertEquals(SubscriptionLinkComparison.Match.SAME,
            SubscriptionLinkComparison.check(saved, "  $saved  "))
        assertEquals(SubscriptionLinkComparison.Match.DIFFERENT,
            SubscriptionLinkComparison.check(saved,
                "https://panel.example.com/sub?token=PRIVATE_B"))
        assertEquals(SubscriptionLinkComparison.Match.INVALID_CANDIDATE,
            SubscriptionLinkComparison.check(saved, "wrong"))
        assertEquals(SubscriptionLinkComparison.Match.NO_SAVED_LINK,
            SubscriptionLinkComparison.check(null, saved))
        for (value in SubscriptionLinkComparison.Match.entries) {
            val message = SubscriptionLinkComparison.message(value)
            assertFalse(message.contains("PRIVATE_A"))
            assertFalse(message.contains("panel.example.com"))
        }
    }
}
