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

    @Test fun preservesGroupMarkersWhenNormalizingCountryLabels() {
        val whitelist = node.replace("Germany",
            "Germany%20%C2%B7%20WhiteList")
        val gaming = node.replace("000000000001", "000000000003")
            .replace("Germany", "Spain%20-%20Gaming")
        val loaded = SubscriptionPayloadParser.nodes(whitelist + "\n" + gaming)
        assertEquals(listOf("Germany · WhiteList", "Spain - Gaming"),
            loaded.map { it.label })
        assertTrue(ServerCollections.isWhiteListLabel(loaded[0].label))
        assertEquals("🇩🇪", ServerRowPresentation.describe(loaded[0], 0).flag)
        assertEquals("🇪🇸", ServerRowPresentation.describe(loaded[1], 1).flag)
    }

    @Test fun recoversExplicitH1CloudWhitelistGroupFromJsonMetadata() {
        val white = JSONObject()
            .put("uri", node)
            .put("groups", JSONArray().put("Белые списки"))
        val ordinary = JSONObject()
            .put("uri", other)
            .put("groups", JSONArray().put("Обычные"))
        val payload = JSONObject().put("profiles", JSONArray()
            .put(white).put(ordinary)).toString()
        val parsed = SubscriptionPayloadParser.nodes(payload)
        assertEquals(2, parsed.size)
        assertTrue(ServerCollections.isWhiteListLabel(parsed[0].label))
        assertFalse(ServerCollections.isWhiteListLabel(parsed[1].label))
        assertEquals(1, parsed.count {
            ServerCollections.isWhiteListLabel(it.label)
        })
        assertEquals("example.org",
            VlessRealityConfig.outbound(parsed[0].uri).getString("server"))
    }

    @Test fun booleanWhitelistMarkerIsNotInferredFromCountry() {
        val payload = JSONObject().put("servers", JSONArray()
            .put(JSONObject().put("uri", node).put("is_whitelist", true))
            .put(JSONObject().put("uri", other).put("is_whitelist", false))
        ).toString()
        val parsed = SubscriptionPayloadParser.nodes(payload)
        assertEquals(2, parsed.size)
        assertTrue(ServerCollections.isWhiteListLabel(parsed[0].label))
        assertFalse(ServerCollections.isWhiteListLabel(parsed[1].label))
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

    @Test fun singBoxRealityJsonKeepsGrpcAndConnectableTls() {
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
        assertEquals(2, nodes.size)
        assertEquals(listOf("🇪🇸 Испания", "🇪🇸 Испания"), nodes.map { it.label })
        assertEquals("grpc", SubscriptionNodeSupport.inspect(nodes[0].uri)?.transport)
        assertTrue(SubscriptionNodeSupport.canConnect(nodes[0].uri))
        assertTrue(SubscriptionNodeSupport.canConnect(nodes[1].uri))
    }

    @Test fun importsActualLteXhttpTlsAndGrpcRealityFromJson() {
        val uuid = "00000000-0000-4000-8000-000000000010"
        val base = JSONObject()
            .put("type", "vless")
            .put("server", "tr.example.org")
            .put("server_port", 443)
            .put("uuid", uuid)
            .put("tls", JSONObject()
                .put("enabled", true)
                .put("server_name", "tr.example.org"))
        val lte = JSONObject(base.toString())
            .put("tag", "Турция")
            .put("lte_access", true)
            .put("transport", JSONObject()
                .put("type", "xhttp").put("path", "/lte"))
        val regular = JSONObject(base.toString())
            .put("tag", "Турция обычный")
            .put("uuid", "00000000-0000-4000-8000-000000000011")
            .put("tls", JSONObject(base.getJSONObject("tls").toString())
                .put("reality", JSONObject()
                    .put("enabled", true)
                    .put("public_key", key)))
            .put("transport", JSONObject()
                .put("type", "grpc").put("service_name", "test-service"))
        val json = JSONObject().put("outbounds",
            JSONArray().put(lte).put(regular)).toString()
        val loaded = SubscriptionPayloadParser.nodes(json)
        assertEquals(2, loaded.size)
        assertEquals("xhttp", SubscriptionNodeSupport.inspect(loaded[0].uri)?.transport)
        assertEquals("tls", SubscriptionNodeSupport.inspect(loaded[0].uri)?.security)
        assertTrue(ServerCollections.isWhiteListLabel(loaded[0].label))
        assertEquals("grpc", SubscriptionNodeSupport.inspect(loaded[1].uri)?.transport)
        assertEquals("reality", SubscriptionNodeSupport.inspect(loaded[1].uri)?.security)
        assertFalse(SubscriptionNodeSupport.canConnect(loaded[0].uri))
        assertTrue(SubscriptionNodeSupport.canConnect(loaded[1].uri))
        assertEquals("🇹🇷", ServerRowPresentation.describe(loaded[0], 0).flag)
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
