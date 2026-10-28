package app.vainah.vpn

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.util.Base64

/** Only invented node credentials. Tests never make network requests. */
class SubscriptionPayloadParserTest {
    private val key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    private val node = "vless://00000000-0000-4000-8000-000000000001@example.org:443" +
        "?security=reality&type=tcp&sni=example.org&pbk=" + key +
        "&fp=chrome#Germany"
    private val other = node.replace("000000000001", "000000000002")
        .replace("Germany", "Norway")

    @Test fun parsesPlainAndBase64SubLists() {
        val plain = "# comment\r\n" + node + "\r\n" + other + "\r\n"
        val nodes = SubscriptionPayloadParser.nodes(plain)
        assertEquals(2, nodes.size)
        assertEquals(listOf("🇩🇪 Германия", "Norway"), nodes.map { it.label })
        assertEquals(nodes, SubscriptionPayloadParser.nodes(
            Base64.getEncoder().encodeToString(plain.toByteArray())
        ))
        assertEquals(nodes, SubscriptionPayloadParser.nodes(
            Base64.getUrlEncoder().withoutPadding().encodeToString(plain.toByteArray())
        ))
    }

    @Test fun parsesXrayRealityTcpJson() {
        val user = JSONObject().put("id", "00000000-0000-4000-8000-000000000001")
            .put("flow", "xtls-rprx-vision")
        val settings = JSONObject().put("vnext", JSONArray().put(JSONObject()
            .put("address", "example.org").put("port", 443)
            .put("users", JSONArray().put(user))))
        val reality = JSONObject().put("serverName", "example.org")
            .put("publicKey", key).put("shortId", "1234").put("fingerprint", "chrome")
        val outbound = JSONObject().put("protocol", "vless").put("tag", "Norway")
            .put("settings", settings).put("streamSettings", JSONObject()
                .put("network", "tcp").put("security", "reality")
                .put("realitySettings", reality))
        val nodes = SubscriptionPayloadParser.nodes(JSONObject()
            .put("outbounds", JSONArray().put(outbound)).toString())
        assertEquals(1, nodes.size)
        assertEquals("Norway", nodes.first().label)
        val converted = VlessRealityConfig.outbound(nodes.first().uri)
        assertEquals("example.org", converted.getString("server"))
        assertEquals("xtls-rprx-vision", converted.getString("flow"))
    }

    @Test fun singBoxRealityJsonSkipsGrpcButKeepsTcp() {
        fun item(transport: String?): JSONObject {
            val o = JSONObject().put("type", "vless").put("tag", "Spain")
                .put("server", "example.org").put("server_port", 443)
                .put("uuid", "00000000-0000-4000-8000-000000000001")
                .put("tls", JSONObject().put("enabled", true)
                    .put("server_name", "example.org")
                    .put("utls", JSONObject().put("fingerprint", "chrome"))
                    .put("reality", JSONObject().put("enabled", true)
                        .put("public_key", key)))
            if (transport != null) o.put("transport", JSONObject().put("type", transport))
            return o
        }
        val nodes = SubscriptionPayloadParser.nodes(JSONObject()
            .put("outbounds", JSONArray().put(item("grpc")).put(item(null))).toString())
        assertEquals(1, nodes.size)
        assertEquals("🇪🇸 Испания", nodes.first().label)
    }

    @Test fun acceptsSimpleJsonLinkLists() {
        val list = JSONObject().put("links", JSONArray().put(node).put(other))
        assertEquals(2, SubscriptionPayloadParser.nodes(list.toString()).size)
    }

    @Test fun rejectsUnsupportedJsonAndInvalidNodes() {
        assertThrows(IllegalArgumentException::class.java) {
            SubscriptionPayloadParser.nodes("{\"outbounds\":[{\"type\":\"direct\"}]}")
        }
        assertThrows(IllegalArgumentException::class.java) {
            SubscriptionPayloadParser.nodes("vless://not-a-uuid@example.org:443")
        }
        assertThrows(IllegalArgumentException::class.java) {
            SubscriptionPayloadParser.nodes("{\"links\":[\"https://example.net/not-a-node\"]}")
        }
    }

    @Test fun capsDocumentSizeAndNumberOfServers() {
        assertThrows(IllegalArgumentException::class.java) {
            SubscriptionPayloadParser.nodes("x".repeat(262145))
        }
        val many = (1..51).joinToString("\n") {
            node.replace("000000000001", it.toString().padStart(12, '0'))
        }
        assertThrows(IllegalArgumentException::class.java) {
            SubscriptionPayloadParser.nodes(many)
        }
    }

    @Test fun removesExactDuplicatesAndPreservesOrder() {
        assertEquals(
            listOf(node, other),
            SubscriptionPayloadParser.nodes(node + "\n" + node + "\n" + other)
                .map { it.uri }
        )
    }
}
