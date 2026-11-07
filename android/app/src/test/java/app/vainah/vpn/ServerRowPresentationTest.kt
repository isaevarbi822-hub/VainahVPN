package app.vainah.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ServerRowPresentationTest {
    private val realFormat = "vless://b0d514b3-d2b7-4eee-a88d-3f7a7a891000@" +
        "example.org:443?security=reality&type=tcp&sni=example.com&pbk=testpublickey#Node"

    private fun node(label: String, uri: String = realFormat) =
        VainahNode(label, uri)

    @Test fun flagsMatchOnlyActualServerLabels() {
        val countries = mapOf(
            "Турция LTE" to ("🇹🇷" to "Турция"),
            "ШВЕЙЦАРИЯ" to ("🇨🇭" to "Швейцария"),
            "🇪🇸 Испания" to ("🇪🇸" to "Испания"),
            "США" to ("🇺🇸" to "США"),
            "Албания" to ("🇦🇱" to "Албания"),
            "Беларусь" to ("🇧🇾" to "Беларусь"),
            "Литва" to ("🇱🇹" to "Литва"),
            "Молдова" to ("🇲🇩" to "Молдова"),
            "Финляндия" to ("🇫🇮" to "Финляндия"),
            "Польша" to ("🇵🇱" to "Польша"),
            "ГЕРМАНИЯ" to ("🇩🇪" to "Германия"),
            "Швеция" to ("🇸🇪" to "Швеция")
        )
        for ((name, expected) in countries) {
            val presented = ServerRowPresentation.describe(node(name), 0)
            assertEquals(name, expected.first, presented.flag)
            assertEquals(name, expected.second, presented.country)
            assertEquals(name, "VLESS / TCP / REALITY", presented.subtitle)
        }
    }

    @Test fun labelIsNeverReplacedWithPrivateEndpointCredentials() {
        val privateLabel = "vless://secret@server.example/?pbk=private"
        val presented = ServerRowPresentation.describe(node(privateLabel), 3)
        assertEquals("Локация 4", presented.title)
        assertEquals("🌐", presented.flag)
        assertFalse(presented.title.contains("secret"))
        assertFalse(presented.title.contains("pbk"))
        assertFalse(presented.subtitle.contains("example.org"))
    }

    @Test fun multipleRealNodesWithSameCountryAreDisambiguatedInOrder() {
        val nodes = listOf(
            node("🇩🇪 Германия", realFormat),
            node("🇩🇪 Германия", realFormat.replace("example.org", "vpn-two.example.org")),
            node("🇵🇱 Польша", realFormat.replace("example.org", "vpn-three.example.org"))
        )
        val rows = ServerRowPresentation.describeList(nodes)
        assertEquals(listOf("Германия · 1", "Германия · 2", "Польша"),
            rows.map { it.title })
        assertEquals(listOf("🇩🇪", "🇩🇪", "🇵🇱"), rows.map { it.flag })
        assertEquals(3, rows.size)
    }

    @Test fun doesNotPretendUnsupportedTransportsAreFunctional() {
        val unsupported = realFormat.replace("type=tcp", "type=grpc")
        val row = ServerRowPresentation.describe(node("Испания", unsupported), 0)
        assertEquals("Формат не подтверждён", row.subtitle)
        assertEquals("unknown", row.transport)
        assertTrue(row.subtitle.contains("не подтверждён"))
    }

    @Test fun onlySufficientRealTcpProbesYieldNumbers() {
        assertEquals("н/д", ServerRowPresentation.latency(null))
        assertEquals("н/д", ServerRowPresentation.latency(
            ServerTcpObservation(0, 3, listOf(30))
        ))
        assertEquals("н/д", ServerRowPresentation.latency(
            ServerTcpObservation(0, 3, emptyList())
        ))
        assertEquals("TCP 52 мс", ServerRowPresentation.latency(
            ServerTcpObservation(0, 3, listOf(51, 52, 100))
        ))
        assertEquals("н/д", ServerRowPresentation.latency(
            ServerTcpObservation(0, 1, listOf(20, 20, 20))
        ))
    }
}
