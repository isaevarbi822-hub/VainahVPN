package app.vainah.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ServerTcpSelectorTest {
    private fun obs(index: Int, vararg durations: Int) =
        ServerTcpObservation(index, ServerTcpSelector.ATTEMPTS_PER_NODE, durations.toList())

    private fun vless(host: String, port: Int): VainahNode =
        VainahNode(
            "Location", "vless://b0d514b3-d2b7-4eee-a88d-3f7a7a891000@" +
                host + ":" + port +
                "?security=reality&type=tcp&sni=example.com&pbk=not-a-real-key#Location"
        )

    @Test fun choosesLowestObservedMedianNotListOrder() {
        assertEquals(2, ServerTcpSelector.best(listOf(
            obs(0, 155, 160, 150),
            obs(1, 80, 90, 800),
            obs(2, 31, 32, 32),
        )))
    }

    @Test fun neverRanksMissingOrSingleSuccessfulMeasurement() {
        assertNull(ServerTcpSelector.best(listOf(
            obs(0), obs(1, 10), obs(2, -1, 90000)
        )))
        assertEquals(1, ServerTcpSelector.best(listOf(
            obs(0, 5), obs(1, 50, 60)
        )))
    }

    @Test fun tiePrefersReliabilityThenOriginalSubscriptionOrder() {
        assertEquals(2, ServerTcpSelector.best(listOf(
            obs(1, 25, 25), obs(2, 25, 25, 25)
        )))
        assertEquals(1, ServerTcpSelector.best(listOf(
            obs(2, 25, 25, 25), obs(1, 25, 25, 25)
        )))
    }

    @Test fun noSyntheticPingOrInvalidEndpoint() {
        assertNull(ServerTcpSelector.best(emptyList()))
        assertNull(ServerTcpSelector.endpoint(VainahNode("bad", "https://example.com")))
        assertNull(ServerTcpSelector.endpoint(VainahNode("bad", "vless://not-valid")))
        assertEquals("vpn.example.org" to 443,
            ServerTcpSelector.endpoint(vless("vpn.example.org", 443)))
        assertNull(ServerTcpSelector.endpoint(vless("vpn.example.org", 65536)))
        assertEquals(8, ServerTcpSelector.MAX_PROBED_NODES)
        assertTrue(ServerTcpSelector.CONNECT_TIMEOUT_MS in 500..2000)
    }
}
