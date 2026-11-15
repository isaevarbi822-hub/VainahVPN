package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test
import java.net.HttpURLConnection

class DirectVlessImportTest {
    private val vless = "vless://00000000-0000-4000-8000-000000000001@example.org:443" +
        "?security=reality&type=tcp&sni=example.org" +
        "&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA&fp=chrome#Poland"

    @Test fun acceptsLegitimateDirectRealityKeyAndHttpsSubscription() {
        assertEquals(vless, SubscriptionInput.validate(vless))
        assertEquals("https://panel.example.com/sub?token=PRIVATE",
            SubscriptionInput.validate(" https://panel.example.com/sub?token=PRIVATE "))
        assertTrue(SubscriptionInput.isDirectKey(vless))
    }

    @Test fun localVlessParsingMakesNoSubscriptionHttpRequest() {
        var calls = 0
        val nodes = SubscriptionServers.loadNodesWithConnection(vless) { _ ->
            calls++
            throw AssertionError("Direct VLESS key must never use HTTPS")
        }
        assertEquals(0, calls)
        assertEquals(1, nodes.size)
        assertEquals("🇵🇱 Польша", nodes[0].label)
        assertEquals(vless, nodes[0].uri)
    }

    @Test fun acceptsDirectGrpcAndTlsKeysWithoutNetworkRequests() {
        val grpc = vless.replace("type=tcp", "type=grpc") + "&serviceName=vpn"
        assertEquals(grpc, SubscriptionInput.validate(grpc))
        val tls = vless.replace("security=reality", "security=tls")
            .replace("&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "")
        assertEquals(tls, SubscriptionInput.validate(tls))
    }

    @Test fun rejectsInvalidDirectKeysWithoutNetworkOrSecretsInUi() {
        val bad = listOf(
            "vless://garbage@example.org:443?security=reality&type=tcp",
            "vless://00000000-0000-4000-8000-000000000001@example.org:443?security=none",
            "http://example.org/sub",
            "ftp://example.org/sub",
            "vless://00000000-0000-4000-8000-000000000001@example.org:443?security=reality&type=xhttp",
            "https://example.org/x\nhttps://example.org/y"
        )
        for (key in bad) assertNull(SubscriptionInput.validate(key))
    }
}
