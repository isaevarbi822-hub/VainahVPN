package app.vainah.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ServerDirectoryTest {
    private val prefix = "vless://b0d514b3-d2b7-4eee-a88d-3f7a7a891000@"
    private val suffix = ":443?security=reality&type=tcp&sni=example.com&pbk=publickey#Node"
    private fun node(title: String, host: String) =
        VainahNode(title, prefix + host + suffix)

    private val nodes = listOf(
        node("🇩🇪 Германия", "de.example.org"),
        node("🇵🇱 Польша", "pl.example.org"),
        node("🇸🇪 Швеция", "se.example.org"),
        node("🇩🇪 Германия", "de2.example.org"),
    )

    @Test fun localSearchMatchesCountryCaseInsensitiveWithoutUrlExposure() {
        val rows = ServerDirectory.view(nodes, emptySet(), "гЕрМаН", false,
            ServerSort.SUBSCRIPTION)
        assertEquals(listOf(0, 3), rows.map { it.index })
        assertEquals(listOf("Германия · 1", "Германия · 2"),
            rows.map { it.info.title })
        assertTrue(rows.none { it.info.title.contains("example.org") })
        assertEquals(0, ServerDirectory.view(nodes, emptySet(), "vless://", false,
            ServerSort.SUBSCRIPTION).size)
    }

    @Test fun favoritesAreFirstAndOnlyFavoritesCanBeFiltered() {
        val id = ServerDirectory.identity(nodes[2].uri)
        val rows = ServerDirectory.view(nodes, setOf(id), "", false,
            ServerSort.SUBSCRIPTION)
        assertEquals(listOf(2, 0, 1, 3), rows.map { it.index })
        assertTrue(rows.first().favorite)
        val only = ServerDirectory.view(nodes, setOf(id), "", true,
            ServerSort.SUBSCRIPTION)
        assertEquals(listOf(2), only.map { it.index })
        val missing = ServerDirectory.view(nodes, setOf(id), "Польша", true,
            ServerSort.SUBSCRIPTION)
        assertTrue(missing.isEmpty())
    }

    @Test fun sortingByCountryUsesRealLabelAndStableOrder() {
        val rows = ServerDirectory.view(nodes, emptySet(), "", false,
            ServerSort.COUNTRY)
        assertEquals(listOf(0, 3, 1, 2), rows.map { it.index })
    }

    @Test fun measuredSortingNeverInventsPingFromMissingSamples() {
        val results = listOf(
            ServerTcpObservation(0, 3, listOf(95, 100, 110)),
            ServerTcpObservation(1, 3, listOf(20)),
            ServerTcpObservation(2, 3, listOf(52, 60, 56)),
        )
        val rows = ServerDirectory.view(nodes, emptySet(), "", false,
            ServerSort.MEASURED_TCP, results)
        assertEquals(listOf(2, 0, 1, 3), rows.map { it.index })
        assertEquals(56, rows.first().measuredTcpMs)
        assertEquals(null, rows[2].measuredTcpMs)
        assertEquals(null, rows[3].measuredTcpMs)
        assertEquals(listOf(0, 1, 2, 3), ServerDirectory.view(
            nodes, emptySet(), "", false, ServerSort.SUBSCRIPTION, results
        ).map { it.index })
    }

    @Test fun idsAreDeterministicHashesNotCredentialsOrHostnames() {
        val id = ServerDirectory.identity(nodes[0].uri)
        assertEquals(64, id.length)
        assertTrue(ServerDirectory.validId(id))
        assertFalse(id.contains("vless"))
        assertFalse(id.contains("example.org"))
        assertEquals(id, ServerDirectory.identity(nodes[0].uri))
        assertFalse(ServerDirectory.validId(id.uppercase()))
        assertFalse(ServerDirectory.validId("vless://secret"))
        assertEquals(20, ServerDirectory.MAX_FAVORITES)
    }

    @Test fun noNodesOrUnmatchedQueryHaveNoSyntheticLocations() {
        assertTrue(ServerDirectory.view(emptyList(), emptySet(), "", false,
            ServerSort.SUBSCRIPTION).isEmpty())
        assertTrue(ServerDirectory.view(nodes, emptySet(), "Новая Зеландия", false,
            ServerSort.COUNTRY).isEmpty())
        val ids = nodes.map { ServerDirectory.identity(it.uri) }.toSet()
        assertEquals(nodes.size, ServerDirectory.view(nodes, ids, "", true,
            ServerSort.SUBSCRIPTION).size)
    }
}
