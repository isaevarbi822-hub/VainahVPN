package app.vainah.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ServerCollectionsTest {
    private fun row(
        index: Int,
        title: String,
        favorite: Boolean = false,
        tcp: Int? = null,
    ) = ServerDirectoryEntry(
        index = index,
        info = ServerRowInfo(
            title = title,
            flag = "🌐",
            subtitle = "VLESS / TCP / REALITY",
            transport = "tcp",
            country = null,
        ),
        favorite = favorite,
        measuredTcpMs = tcp,
    )

    private val all = listOf(
        row(0, "🇧🇾 Беларусь · Белые списки", tcp = 49),
        row(1, "🇩🇪 Germany · Gaming", favorite = true),
        row(2, "🇵🇱 Польша · Streaming"),
        row(3, "🇪🇸 Испания"),
        row(4, "🇫🇷 WhiteList Fast"),
    )

    @Test fun whitelistCategoryContainsOnlyExplicitlyMarkedSubscriptionNodes() {
        assertEquals(
            listOf(0, 4),
            ServerCollections.filter(all, ServerCollection.WHITELIST).map { it.index },
        )
        assertTrue(ServerCollections.isWhiteListLabel("БЕЛЫЕ СПИСКИ 01"))
        assertTrue(ServerCollections.isWhiteListLabel("White_List Secure"))
        assertTrue(ServerCollections.isWhiteListLabel("Белые-списки · 01"))
        assertTrue(ServerCollections.isWhiteListLabel("🇹🇷 Турция · LTE-доступ"))
        assertTrue(ServerCollections.isWhiteListLabel("Turkey LTE"))
        assertFalse(ServerCollections.isWhiteListLabel("Satellite relay"))
        assertFalse(ServerCollections.isWhiteListLabel("🇧🇾 Belarus · Minsk"))
        assertFalse(ServerCollections.isWhiteListLabel("Fast VPN"))
        assertTrue(ServerCollections.filter(
            listOf(row(0, "🇧🇾 Беларусь")),
            ServerCollection.WHITELIST,
        ).isEmpty())
    }

    @Test fun locallyGroupedNodesAreRealSubscriptionNodesNotInventedEndpoints() {
        val manuallyGrouped = row(7, "🇷🇺 Россия · TCP")
            .copy(manualWhitelist = true)
        val ordinary = row(8, "🇳🇴 Норвегия")
        assertEquals(listOf(7), ServerCollections.filter(
            listOf(manuallyGrouped, ordinary), ServerCollection.WHITELIST
        ).map { it.index })
        assertFalse(ServerCollections.isWhiteListLabel(ordinary.info.title))
    }

    @Test fun favoriteGamingAndStreamingCategoriesReflectOnlyRealLabels() {
        assertEquals(5, ServerCollections.filter(all, ServerCollection.ALL).size)
        assertEquals(listOf(1), ServerCollections.filter(
            all, ServerCollection.GAMES,
        ).map { it.index })
        assertEquals(listOf(2), ServerCollections.filter(
            all, ServerCollection.STREAMING,
        ).map { it.index })
        assertEquals(listOf(1), ServerCollections.filter(
            all, ServerCollection.FAVORITES,
        ).map { it.index })
    }

    @Test fun recommendedAndFastOnlyUseFavoritesOrActualTcpObservations() {
        assertEquals(listOf(0, 1), ServerCollections.filter(
            all, ServerCollection.RECOMMENDED,
        ).map { it.index })
        assertEquals(listOf(0), ServerCollections.filter(
            all, ServerCollection.FAST,
        ).map { it.index })
    }

    @Test fun missingWhiteListDoesNotCreateFictitiousServers() {
        assertTrue(ServerCollections.filter(
            emptyList(), ServerCollection.WHITELIST,
        ).isEmpty())
        assertTrue(ServerCollections.emptyMessage(
            ServerCollection.WHITELIST, true,
        ).contains("H1Cloud"))
        assertTrue(ServerCollections.emptyMessage(
            ServerCollection.WHITELIST, false,
        ).contains("нет серверов"))
    }
}
