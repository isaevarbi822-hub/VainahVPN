package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test
import java.net.HttpURLConnection
import java.net.URL

class SubscriptionHwidHeadersTest {
    private class Request : HttpURLConnection(URL("https://panel.example.com/sub")) {
        override fun disconnect() {}
        override fun usingProxy() = false
        override fun connect() {}
    }

    @Test fun disabledByDefaultRequestDoesNotSendDeviceIdentity() {
        val request = Request()
        SubscriptionServers.configureConnection(request)
        assertNull(request.getRequestProperty("X-HWID"))
        assertNull(request.getRequestProperty("X-Ver-Os"))
        assertNull(request.getRequestProperty("X-Device-Model"))
        assertEquals("VainahVPN-Android/" + BuildConfig.VERSION_NAME,
            request.getRequestProperty("User-Agent"))
    }

    @Test fun enabledUsesOnlyValidAppSpecificHeaders() {
        val id = "b23d22bc-6188-4ffd-8dce-f7c5ee9ca10a"
        val headers = SubscriptionHwidHeaders.build(id,"16","SM-S938B")
        assertEquals(id, headers["X-HWID"])
        val request = Request()
        SubscriptionServers.configureConnection(request, headers)
        assertEquals(id, request.getRequestProperty("X-HWID"))
        assertEquals("Android", request.getRequestProperty("X-Device-Os"))
        assertEquals("16", request.getRequestProperty("X-Ver-Os"))
        assertEquals("SM-S938B", request.getRequestProperty("X-Device-Model"))
        assertEquals(false, request.instanceFollowRedirects)
    }

    @Test fun invalidIdentifiersAndUntrustedKeysAreNeverTransmitted() {
        val forged = mapOf(
            "X-HWID" to "bad\nsecret",
            "Authorization" to "Bearer private-token",
            "Cookie" to "private=token",
            "X-Device-Model" to "host\nnewline"
        )
        val request = Request()
        SubscriptionServers.configureConnection(request, forged)
        assertNull(request.getRequestProperty("X-HWID"))
        assertNull(request.getRequestProperty("X-Device-Model"))
        assertNull(request.getRequestProperty("Authorization"))
        assertNull(request.getRequestProperty("Cookie"))
        assertTrue(SubscriptionHwidHeaders.build("bad", "16", "SM-S938B").isEmpty())
    }

    @Test fun deviceMetadataIsBoundedToSafeAscii() {
        val headers = SubscriptionHwidHeaders.build(
            "b23d22bc-6188-4ffd-8dce-f7c5ee9ca10a",
            "16\r\nEXTRA:secret",
            "SM-S938B".repeat(20)
        )
        assertFalse(headers["X-Ver-Os"].orEmpty().contains("\r"))
        assertFalse(headers["X-Ver-Os"].orEmpty().contains("\n"))
        assertTrue(headers["X-Device-Model"].orEmpty().length <= 64)
    }
}
