package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class TunRoutePolicyTest {
    @Test fun missingLegacyIpv4RoutesRequireFullTunnelFallback() {
        assertTrue(TunRoutePolicy.needsDefaultRoute(true, true, 0))
    }

    @Test fun missingLegacyIpv6RoutesRequireFullTunnelFallback() {
        assertTrue(TunRoutePolicy.needsDefaultRoute(true, true, 0))
    }

    @Test fun existingRoutesRemainAuthoritative() {
        assertFalse(TunRoutePolicy.needsDefaultRoute(true, true, 1))
        assertFalse(TunRoutePolicy.needsDefaultRoute(true, true, 3))
    }

    @Test fun neverCreateRoutesForDisabledOrUnconfiguredFamilies() {
        assertFalse(TunRoutePolicy.needsDefaultRoute(false, true, 0))
        assertFalse(TunRoutePolicy.needsDefaultRoute(true, false, 0))
        assertFalse(TunRoutePolicy.needsDefaultRoute(false, false, 0))
    }

    @Test fun invalidRouteCounterFailsClosed() {
        assertThrows(IllegalArgumentException::class.java) {
            TunRoutePolicy.needsDefaultRoute(true, true, -1)
        }
    }
}
