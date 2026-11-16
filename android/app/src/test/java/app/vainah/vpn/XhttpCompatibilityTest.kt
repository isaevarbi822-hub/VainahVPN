package app.vainah.vpn

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.net.URLEncoder

/** Invented server and key only. Never depends on real H1Cloud credentials. */
class XhttpCompatibilityTest {
    private val base =
        "vless://00000000-0000-4000-8000-000000000001@example.org:443" +
        "?security=reality&type=xhttp&sni=example.org" +
        "&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA&fp=chrome"

    private fun encoded(extra: JSONObject): String =
        base + "&extra=" + URLEncoder.encode(extra.toString(), "UTF-8")

    @Test fun directXrayExtraRetainsWireCriticalOptions() {
        val extra = JSONObject()
            .put("mode", "stream-up")
            .put("path", "/turkey/ip")
            .put("host", "front.example.org")
            .put("xPaddingBytes", "400-800")
            .put("noGRPCHeader", true)
            .put("scMinPostsIntervalMs", "30-60")
        val outbound = VlessRealityConfig.outbound(encoded(extra))
        val transport = outbound.getJSONObject("transport")
        assertEquals("xhttp", transport.getString("type"))
        assertEquals("stream-up", transport.getString("mode"))
        assertEquals("/turkey/ip", transport.getString("path"))
        assertEquals("front.example.org", transport.getString("host"))
        assertEquals("400-800", transport.getString("x_padding_bytes"))
        assertTrue(transport.getBoolean("no_grpc_header"))
        assertEquals("30-60", transport.getString("sc_min_posts_interval_ms"))
        assertTrue(outbound.getJSONObject("tls").getJSONObject("reality")
            .getBoolean("enabled"))
    }

    @Test fun xrayJsonExtraSurvivesBothSubscriptionImportAndLibboxConversion() {
        val xhttp = JSONObject().put("mode", "packet-up")
            .put("path", "/t1")
            .put("extra", JSONObject()
                .put("noGRPCHeader", true)
                .put("xPaddingBytes", "100-1000")
                .put("scMaxEachPostBytes", "200000-400000"))
        val user = JSONObject()
            .put("id", "00000000-0000-4000-8000-000000000001")
        val server = JSONObject()
            .put("address", "example.org")
            .put("port", 443)
            .put("users", JSONArray().put(user))
        val stream = JSONObject()
            .put("network", "xhttp")
            .put("security", "reality")
            .put("realitySettings", JSONObject()
                .put("serverName", "example.org")
                .put("publicKey", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"))
            .put("xhttpSettings", xhttp)
        val outbound = JSONObject()
            .put("protocol", "vless")
            .put("tag", "Турция · 1")
            .put("streamSettings", stream)
            .put("settings", JSONObject().put("vnext", JSONArray().put(server)))
        val config = JSONObject()
            .put("outbounds", JSONArray().put(outbound))
        val nodes = SubscriptionPayloadParser.nodes(config.toString())
        assertEquals(1, nodes.size)
        assertEquals("Турция · 1", nodes.single().label)
        val transport = VlessRealityConfig.outbound(nodes.single().uri)
            .getJSONObject("transport")
        assertEquals("/t1", transport.getString("path"))
        assertTrue(transport.getBoolean("no_grpc_header"))
        assertEquals("100-1000", transport.getString("x_padding_bytes"))
        assertEquals("200000-400000",
            transport.getString("sc_max_each_post_bytes"))
    }

    @Test fun singboxTransportFieldsAndHeadersStayIntact() {
        val transport = JSONObject().put("type", "xhttp")
            .put("path", "/turkey")
            .put("no_grpc_header", true)
            .put("headers", JSONObject().put("X-Test", "custom"))
        val node = JSONObject().put("type", "vless")
            .put("server", "example.org").put("server_port", 443)
            .put("uuid", "00000000-0000-4000-8000-000000000001")
            .put("tag", "Турция · IP")
            .put("tls", JSONObject().put("enabled", true)
                .put("server_name", "example.org")
                .put("reality", JSONObject().put("enabled", true)
                    .put("public_key",
                        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")))
            .put("transport", transport)
        val imported = SubscriptionPayloadParser.nodes(
            JSONObject().put("outbounds", JSONArray().put(node)).toString())
        val converted = VlessRealityConfig.outbound(imported.single().uri)
            .getJSONObject("transport")
        assertTrue(converted.getBoolean("no_grpc_header"))
        assertEquals("custom", converted.getJSONObject("headers").getString("X-Test"))
    }

    @Test fun xrayTlsAlpnSurvivesJsonSubscriptionToNativeXhttp() {
        val server = JSONObject()
            .put("address", "example.org").put("port", 443)
            .put("users", JSONArray().put(JSONObject().put(
                "id", "00000000-0000-4000-8000-000000000001")))
        val stream = JSONObject()
            .put("security", "tls")
            .put("network", "xhttp")
            .put("tlsSettings", JSONObject()
                .put("serverName", "example.org")
                .put("alpn", JSONArray().put("h2").put("http/1.1")))
            .put("xhttpSettings", JSONObject()
                .put("path", "/turkey")
                .put("mode", "packet-up"))
        val xray = JSONObject()
            .put("protocol", "vless")
            .put("tag", "Турция · IP")
            .put("streamSettings", stream)
            .put("settings", JSONObject().put(
                "vnext", JSONArray().put(server)))
        val nodes = SubscriptionPayloadParser.nodes(JSONObject().put(
            "outbounds", JSONArray().put(xray)).toString())
        assertEquals(1, nodes.size)
        val importedAlpn = VlessRealityConfig.outbound(nodes.single().uri)
            .getJSONObject("tls").getJSONArray("alpn")
        assertEquals("h2", importedAlpn.getString(0))
        assertEquals("http/1.1", importedAlpn.getString(1))
    }

    @Test fun rejectsUnsupportedOrMalformedExtraInsteadOfSilentlyDowngrading() {
        assertFalse(SubscriptionNodeSupport.canConnect(encoded(
            JSONObject().put("downloadSettings", JSONObject().put("address", "other"))
        )))
        assertThrows(IllegalArgumentException::class.java) {
            VlessRealityConfig.outbound(encoded(JSONObject()
                .put("headers", JSONObject().put("Host", "wrong.example"))))
        }
        assertThrows(IllegalArgumentException::class.java) {
            VlessRealityConfig.outbound(encoded(JSONObject()
                .put("mode", "not-a-real-mode")))
        }
        assertTrue(SubscriptionNodeSupport.canConnect(encoded(JSONObject()
            .put("mode", "packet-up"))))
    }

    @Test fun allowsKnownServerOnlyXrayFieldsWithoutChangingTransport() {
        val p = VlessRealityConfig.outbound(encoded(
            JSONObject().put("noSSEHeader", true).put("mode", "packet-up")
        )).getJSONObject("transport")
        assertFalse(p.has("no_sse_header"))
        assertEquals("packet-up", p.getString("mode"))
    }
}
