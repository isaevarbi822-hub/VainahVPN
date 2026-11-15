package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class TurkeyLteGroupsTest {
    private fun node(label: String, index: Int): VainahNode =
        VainahNode(
            label,
            "vless://00000000-0000-4000-8000-00000000000${index}@" +
                "example.org:443?security=reality&type=tcp&sni=example.org" +
                "&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA#Test"
        )

    @Test fun matchesOnlyTwoExplicitlyRequestedTurkeyNodes() {
        for (label in listOf(
            "Турция · 1", "Турция · IP", "🇹🇷 Турция · 1",
            "🇹🇷 Турция · IP", "Turkey - IP", "Türkiye • 1"
        )) {
            assertTrue("Expected matched: $label", TurkeyLteGroups.isPreferredLte(label))
        }
        for (label in listOf(
            "Турция · 2", "Турция · 3", "Турция · 10",
            "Турция · IP extra", "🇹🇷 Турция",
            "Албания · 1", "Turkey LTE",
            "vless://secret@example.org:443"
        )) {
            assertFalse("Must not match: $label", TurkeyLteGroups.isPreferredLte(label))
        }
    }

    @Test fun usesOnlyActualImportedUrisAndCreatesNoServers() {
        val nodes = listOf(
            node("Турция · 1", 1), node("Турция · IP", 2),
            node("Турция · 2", 3), node("Албания · 1", 4)
        )
        val matches = TurkeyLteGroups.matchingIds(nodes)
        assertEquals(2, matches.size)
        assertTrue(matches.contains(ServerDirectory.identity(nodes[0].uri)))
        assertTrue(matches.contains(ServerDirectory.identity(nodes[1].uri)))
        assertEquals(emptySet<String>(), TurkeyLteGroups.matchingIds(emptyList()))
        assertEquals(4, nodes.size)
        val entries = ServerDirectory.view(
            nodes, emptySet(), "", false, ServerSort.SUBSCRIPTION,
            manualWhiteListIds = matches
        )
        assertEquals(listOf(0, 1),
            ServerCollections.filter(entries, ServerCollection.WHITELIST)
                .map { it.index }
        )
    }
}
