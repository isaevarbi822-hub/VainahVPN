package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test
import java.net.InetAddress

class RouteCoverageTest {
    private fun prefix(address: String, length: Int): Pair<ByteArray, Int> =
        InetAddress.getByName(address).address to length

    @Test fun singleIpv4DefaultRouteCoversEverything() {
        assertTrue(RouteCoverage.coversAll(4, listOf(prefix("0.0.0.0", 0))))
    }

    @Test fun splitIpv4DefaultRoutesAreRecognized() {
        assertTrue(RouteCoverage.coversAll(4, listOf(
            prefix("128.0.0.0", 1), prefix("0.0.0.0", 1)
        )))
    }

    @Test fun splitIpv6DefaultRoutesAreRecognized() {
        assertTrue(RouteCoverage.coversAll(16, listOf(
            prefix("8000::", 1), prefix("::", 1)
        )))
    }

    @Test fun gapsInRoutesAreNotCalledFullCoverage() {
        assertFalse(RouteCoverage.coversAll(4, listOf(prefix("0.0.0.0", 1))))
        assertFalse(RouteCoverage.coversAll(16, listOf(prefix("::", 1))))
        assertFalse(RouteCoverage.coversAll(4, emptyList()))
    }

    @Test fun overlappingAndUnsortedRoutesCanStillCoverEverything() {
        assertTrue(RouteCoverage.coversAll(4, listOf(
            prefix("64.0.0.0", 2), prefix("0.0.0.0", 2),
            prefix("128.0.0.0", 1), prefix("64.0.0.0", 2)
        )))
    }

    @Test fun ignoresMalformedPrefixesAndOtherIpFamilies() {
        assertFalse(RouteCoverage.coversAll(4, listOf(prefix("::", 0))))
        assertFalse(RouteCoverage.coversAll(4, listOf(prefix("0.0.0.0", 33))))
        assertThrows(IllegalArgumentException::class.java) {
            RouteCoverage.coversAll(5, emptyList())
        }
    }
}
