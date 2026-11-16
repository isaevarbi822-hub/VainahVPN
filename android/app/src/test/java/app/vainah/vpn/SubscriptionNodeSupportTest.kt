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
        assertEquals(BuildConfig.VAINAH_XHTTP_ENGINE_ENABLED,
            SubscriptionNodeSupport.canConnect(xhttpTls))
    }

    @Test fun invalidAndUnrelatedEndpointsNeverGetImported() {
        assertNull(SubscriptionNodeSupport.inspect("https://example.org"))
        assertNull(SubscriptionNodeSupport.inspect("vless://not-a-uuid@tr.example.org:443"))
        assertNull(SubscriptionNodeSupport.inspect(start + "?security=none&type=tcp"))
        assertNull(SubscriptionNodeSupport.inspect(start + "?security=tls&type=unknown"))
        assertNull(SubscriptionNodeSupport.inspect(start + "?security=reality&type=grpc"))
    }

    @Test fun unsupportedXhttpExtraIsNotMistakenForMissingEngine() {
        val raw = xhttpTls + "&extra=" + java.net.URLEncoder.encode(
            """{"downloadSettings":{"address":"other.example.org"}}""", "UTF-8")
        val details = SubscriptionNodeSupport.inspect(raw)
        assertNotNull(details)
        assertEquals("VLESS / XHTTP / TLS", details?.subtitle)
        // A missing XHTTP-native build takes priority over node validation.
        val code = if (BuildConfig.VAINAH_XHTTP_ENGINE_ENABLED)
            "xhttp_extra_unsupported" else "native_xhttp_missing"
        assertEquals(code, details?.rejectionCode)
        assertFalse(details!!.connectable)
        assertFalse(SubscriptionNodeSupport.safeBlockMessage(details)
            .contains("other.example.org"))
        assertFalse(SubscriptionNodeSupport.safeBlockMessage(details)
            .contains("00000000-0000-4000"))
    }

    @Test fun incompatibleFlowOnTlsXhttpGivesSafeProfileExplanation() {
        val details = SubscriptionNodeSupport.inspect(
            xhttpTls + "&flow=xtls-rprx-vision")
        val code = if (BuildConfig.VAINAH_XHTTP_ENGINE_ENABLED)
            "vless_flow_incompatible" else "native_xhttp_missing"
        assertEquals(code, details?.rejectionCode)
        assertFalse(details?.connectable ?: true)
    }

    @Test fun correctlyFormattedXhttpTlsRemainsConnectableInEnabledBuild() {
        val details = SubscriptionNodeSupport.inspect(xhttpTls +
            "&mode=packet-up&x_padding_bytes=100-1000&alpn=h2")
        assertNotNull(details)
        assertEquals(BuildConfig.VAINAH_XHTTP_ENGINE_ENABLED, details?.connectable)
        assertEquals(
            if (BuildConfig.VAINAH_XHTTP_ENGINE_ENABLED) null else "native_xhttp_missing",
            details?.rejectionCode)
    }

    @Test fun sourceMarkersRemainDisplayOnlyAndDoNotUpgradeConnectionSupport() {
        val uri = xhttpTls + "#%D0%A2%D1%83%D1%80%D1%86%D0%B8%D1%8F%20LTE"
        val parsed = SubscriptionPayloadParser.nodes(uri)
        assertEquals(1, parsed.size)
        assertTrue(ServerCollections.isWhiteListLabel(parsed[0].label))
        assertEquals(BuildConfig.VAINAH_XHTTP_ENGINE_ENABLED,
            SubscriptionNodeSupport.canConnect(parsed[0].uri))
        assertEquals("xhttp",
            SubscriptionNodeSupport.inspect(parsed[0].uri)?.transport)
    }
}
