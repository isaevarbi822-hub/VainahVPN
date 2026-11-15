package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

/** Synthetic endpoints only. This does not contact a live VPN provider. */
class SubscriptionNodeSupportTest {
    private val start = "vless://00000000-0000-4000-8000-000000000001@tr.example.org:443"
    private val reality = "?security=reality&type=tcp&sni=tr.example.org" +
        "&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    private val grpc = start + reality.replace("type=tcp", "type=grpc")
    private val xhttpTls = start + "?security=tls&type=xhttp&sni=tr.example.org" +
        "&path=%2Flte%2Fendpoint"

    @Test fun compatibleTcpRealityIsClearlyDistinguishedFromDisplayOnly() {
        val supported = SubscriptionNodeSupport.inspect(start + reality)
        assertNotNull(supported)
        assertTrue(supported!!.connectable)
        assertEquals("VLESS / TCP / REALITY", supported.subtitle)

        assertEquals("VLESS / GRPC / REALITY",
            SubscriptionNodeSupport.inspect(grpc)?.subtitle)
        assertTrue(SubscriptionNodeSupport.canConnect(grpc))
        assertEquals("VLESS / XHTTP / TLS",
            SubscriptionNodeSupport.inspect(xhttpTls)?.subtitle)
        assertFalse(SubscriptionNodeSupport.canConnect(xhttpTls))
    }

    @Test fun invalidAndUnrelatedEndpointsNeverGetImported() {
        assertNull(SubscriptionNodeSupport.inspect("https://example.org"))
        assertNull(SubscriptionNodeSupport.inspect("vless://not-a-uuid@tr.example.org:443"))
        assertNull(SubscriptionNodeSupport.inspect(start + "?security=none&type=tcp"))
        assertNull(SubscriptionNodeSupport.inspect(start + "?security=tls&type=unknown"))
        assertNull(SubscriptionNodeSupport.inspect(start + "?security=reality&type=grpc"))
    }

    @Test fun sourceMarkersRemainDisplayOnlyAndDoNotUpgradeConnectionSupport() {
        val uri = xhttpTls + "#%D0%A2%D1%83%D1%80%D1%86%D0%B8%D1%8F%20LTE"
        val parsed = SubscriptionPayloadParser.nodes(uri)
        assertEquals(1, parsed.size)
        assertTrue(ServerCollections.isWhiteListLabel(parsed[0].label))
        assertFalse(SubscriptionNodeSupport.canConnect(parsed[0].uri))
        assertEquals("xhttp",
            SubscriptionNodeSupport.inspect(parsed[0].uri)?.transport)
    }
}
