package app.vainah.vpn

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

/** Everything here uses a synthetic VLESS profile, never a real subscription. */
class LibboxValidationIsolationTest {
    private val node = "vless://00000000-0000-4000-8000-000000000001@example.org:443" +
        "?security=reality&type=xhttp&sni=example.org" +
        "&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" +
        "&mode=packet-up&path=%2Ftest&x_padding_bytes=100-1000"

    private val example: String get() = VlessRealityConfig.profile(node, "192.0.2.25")

    @Test fun isolatesOptionalXhttpOptions() {
        val result = LibboxValidationIsolation.classify(example) { json ->
            val transport = JSONObject(json).getJSONArray("outbounds")
                .getJSONObject(0).optJSONObject("transport")
            if (transport?.has("x_padding_bytes") == true) {
                throw IllegalArgumentException("private.example/uuid should not be exported")
            }
        }
        assertEquals(LibboxValidationIsolation.TRANSPORT_EXTRAS, result)
    }

    @Test fun distinguishesTransportFromVlessIdentityAndSharedSettings() {
        assertEquals(LibboxValidationIsolation.TRANSPORT,
            LibboxValidationIsolation.classify(example) { json ->
                if (JSONObject(json).getJSONArray("outbounds").getJSONObject(0)
                        .has("transport")) throw IllegalArgumentException("transport")
            })
        assertEquals(LibboxValidationIsolation.OUTBOUND,
            LibboxValidationIsolation.classify(example) { json ->
                if (JSONObject(json).getJSONArray("outbounds").getJSONObject(0)
                        .getString("type") == "vless") throw IllegalArgumentException("vless")
            })
        assertEquals(LibboxValidationIsolation.SHARED,
            LibboxValidationIsolation.classify(example) {
                throw IllegalArgumentException("whatever: secret.example")
            })
    }

    @Test fun failsClosedOnMalformedInputWithoutExportingIt() {
        assertEquals(LibboxValidationIsolation.UNKNOWN,
            LibboxValidationIsolation.classify("private.example", { }))
    }
}
