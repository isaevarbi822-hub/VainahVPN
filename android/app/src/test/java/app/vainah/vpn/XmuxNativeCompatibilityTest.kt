package app.vainah.vpn

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.net.URLEncoder

/** Synthetic profiles only; these cases also run against the pinned native core. */
class XmuxNativeCompatibilityTest {
    private val base = "vless://00000000-0000-4000-8000-000000000001@example.org:443" +
        "?security=reality&type=xhttp&sni=example.org" +
        "&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

    private fun node(xmux: Any): String = base + "&extra=" + URLEncoder.encode(
        JSONObject().put("xmux", xmux).toString(), "UTF-8")

    private fun converted(xmux: Any): JSONObject = VlessRealityConfig.outbound(node(xmux))
        .getJSONObject("transport").getJSONObject("xmux")

    @Test fun emptyRangesStayUnsetRatherThanBecomingExplicitZeroLimits() {
        // The core applies its defaults to an entirely empty section. Replacing
        // empty strings with "0" would instead select an unlimited pool.
        val xmux = converted(JSONObject()
            .put("maxConcurrency", "").put("maxConnections", "  ")
            .put("cMaxReuseTimes", "").put("hMaxRequestTimes", "")
            .put("hMaxReusableSecs", "").put("hKeepAlivePeriod", 0))
        assertEquals("", xmux.getString("max_concurrency"))
        assertEquals("", xmux.getString("max_connections"))
        assertEquals("", xmux.getString("h_max_request_times"))
        assertEquals("0", converted(JSONObject().put("maxConnections", 0))
            .getString("max_connections"))
    }

    @Test fun nativeIntegerStringAndArrayRangeFormsAreAccepted() {
        for (range in listOf<Any>(3, "3", JSONArray().put(3),
            JSONArray().put(3).put(3), " 3 - 3 ")) {
            val xmux = JSONObject().put("maxConnections", range)
                .put("maxConcurrency", JSONArray().put(0))
            assertTrue(SubscriptionNodeSupport.canConnect(node(xmux)))
            assertTrue(converted(xmux).getString("max_connections") in setOf("3", "3-3"))
        }
        assertEquals("2147483647", converted(JSONObject()
            .put("hMaxRequestTimes", Int.MAX_VALUE)).getString("h_max_request_times"))
    }

    @Test fun reversedArrayBoundsCannotHideConflictingActiveLimits() {
        for (range in listOf<Any>("8-0", JSONArray().put(8).put(0),
            " 0 - 8 ", JSONArray().put(8))) {
            val error = assertThrows(IllegalArgumentException::class.java) {
                converted(JSONObject().put("maxConcurrency", range).put("maxConnections", 3))
            }
            assertEquals("Conflicting XHTTP xmux limits", error.message)
        }
        assertEquals("0-8", converted(JSONObject()
            .put("maxConnections", JSONArray().put(8).put(0)))
            .getString("max_connections"))
    }

    @Test fun malformedRangesCannotPassByNumericTruncationOrOverflow() {
        for (range in listOf<Any>(1.5, -1, "1.5", "2147483648", 2147483648L,
            "0-9999999999", JSONArray().put(0).put(0.5), JSONArray(),
            JSONArray().put(1).put(2).put(3), JSONObject(), true)) {
            val error = assertThrows(IllegalArgumentException::class.java) {
                converted(JSONObject().put("maxConnections", range))
            }
            assertEquals("Invalid XHTTP xmux range", error.message)
        }
    }

    @Test fun nullSectionUsesNativeDefaultsButMalformedSectionsStillFail() {
        assertFalse(VlessRealityConfig.outbound(node(JSONObject.NULL))
            .getJSONObject("transport").has("xmux"))
        for (value in listOf<Any>("", 0, JSONArray(), true)) {
            assertThrows(IllegalArgumentException::class.java) { converted(value) }
        }
    }

    @Test fun encodedXmuxObjectHasTheSameNativeMeaning() {
        val settings = JSONObject().put("maxConnections", "3-3")
            .put("maxConcurrency", "").put("hMaxRequestTimes", JSONArray().put(600).put(900))
        assertEquals(converted(settings).toString(), converted(settings.toString()).toString())
        assertEquals(0, converted("{}").length())
        assertTrue(SubscriptionNodeSupport.canConnect(node(settings.toString())))
        for (bad in listOf("{} trailing", "[]", "null", "{", "\"{}\"")) {
            assertEquals("xhttp_xmux_invalid_json", SubscriptionNodeSupport.inspect(node(bad))?.rejectionCode)
        }
    }

    @Test fun rootXmuxErrorsHavePreciseSafeCodes() {
        val sevenFields = JSONObject().put("maxConcurrency", "")
            .put("maxConnections", "").put("cMaxReuseTimes", "")
            .put("hMaxRequestTimes", "").put("hMaxReusableSecs", "")
            .put("hKeepAlivePeriod", 0).put("private_unknown_name", "secret")
        assertEquals("xhttp_xmux_unknown_field", SubscriptionNodeSupport.inspect(node(sevenFields))?.rejectionCode)
        assertEquals("xhttp_xmux_invalid_type", SubscriptionNodeSupport.inspect(node(false))?.rejectionCode)
        assertEquals("xhttp_xmux_too_large", SubscriptionNodeSupport.inspect(node("x".repeat(1025)))?.rejectionCode)
        val manyFields = JSONObject().apply { repeat(13) { put("private_$it", 0) } }
        assertEquals("xhttp_xmux_too_many_fields", SubscriptionNodeSupport.inspect(node(manyFields))?.rejectionCode)
        val info = SubscriptionNodeSupport.safeBlockMessage(SubscriptionNodeSupport.inspect(node(sevenFields)))
        assertFalse(info.contains("secret"))
        assertFalse(info.contains("private_unknown_name"))
    }

    @Test fun bothSubscriptionJsonFormatsPreserveXmuxAndServerEligibility() {
        val xray = JSONObject("""{
          "protocol":"vless", "tag":"Турция · 1",
          "settings":{"vnext":[{"address":"example.org","port":443,
            "users":[{"id":"00000000-0000-4000-8000-000000000001"}]}]},
          "streamSettings":{"security":"tls","network":"xhttp",
            "tlsSettings":{"serverName":"example.org","alpn":["h2"]},
            "xhttpSettings":{"path":"/test","extra":{"xmux":{
              "maxConcurrency":"", "maxConnections":[3], "hMaxRequestTimes":" 600 - 900 "
            }}}}
        }""")
        val singbox = JSONObject("""{
          "type":"vless", "tag":"Турция · 2", "server":"example.org", "server_port":443,
          "uuid":"00000000-0000-4000-8000-000000000001",
          "tls":{"enabled":true,"server_name":"example.org","alpn":["h2"]},
          "transport":{"type":"xhttp","path":"/test","xmux":{
            "max_concurrency":"", "max_connections":[3], "h_max_request_times":" 600 - 900 "
          }}
        }""")
        for (source in listOf(xray, singbox)) {
            val nodes = SubscriptionPayloadParser.nodes(JSONObject()
                .put("outbounds", JSONArray().put(source)).toString())
            assertEquals(1, nodes.size)
            assertTrue(SubscriptionNodeSupport.canConnect(nodes.single().uri))
            val transport = VlessRealityConfig.outbound(nodes.single().uri).getJSONObject("transport")
            assertEquals("xhttp", transport.getString("type"))
            assertEquals("600-900", transport.getJSONObject("xmux").getString("h_max_request_times"))
        }
    }
}
