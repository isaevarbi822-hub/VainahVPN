package app.vainah.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VpnRouteAdvisorTest {
    @Test fun offDoesNotClaimCurrentVpnRoutes() {
        val oldFacts = VpnNetworkFacts(
            visible = true, ipv4DefaultRoute = true, ipv6DefaultRoute = true,
            dnsConfigured = true,
        )
        val result = VpnRouteAdvisor.assess(false, oldFacts)
        assertEquals("vpn_off", result.code)
        assertFalse(result.needsReview)
    }

    @Test fun missingAndroidVpnNetworkNeedsReview() {
        val result = VpnRouteAdvisor.assess(true, VpnNetworkFacts(visible = false))
        assertEquals("vpn_not_visible", result.code)
        assertTrue(result.needsReview)
        assertFalse(result.explanation.contains("утечка доказана"))
    }

    @Test fun unknownDoesNotBecomeNegativeResult() {
        assertEquals("vpn_visibility_unknown",
            VpnRouteAdvisor.assess(true, null).code)
        assertEquals("vpn_routes_incomplete", VpnRouteAdvisor.assess(
            true, VpnNetworkFacts(visible = true)
        ).code)
        assertFalse(VpnRouteAdvisor.assess(
            true, VpnNetworkFacts(visible = true)
        ).needsReview)
    }

    @Test fun missingDnsOrRouteIsReviewNotLeakProof() {
        val result = VpnRouteAdvisor.assess(true, VpnNetworkFacts(
            visible = true, ipv4DefaultRoute = true,
            ipv6DefaultRoute = false, dnsConfigured = false,
        ))
        assertEquals("vpn_routes_review", result.code)
        assertTrue(result.needsReview)
        assertTrue(result.explanation.contains("IPv6"))
        assertTrue(result.explanation.contains("DNS"))
        assertTrue(result.explanation.contains("не проверялись"))
    }

    @Test fun fullyObservedMetadataNeverClaimsSecureTraffic() {
        val result = VpnRouteAdvisor.assess(true, VpnNetworkFacts(
            visible = true, ipv4DefaultRoute = true,
            ipv6DefaultRoute = true, dnsConfigured = true,
        ))
        assertEquals("vpn_routes_present", result.code)
        assertFalse(result.needsReview)
        assertTrue(result.explanation.contains("НЕ подтверждает"))
        assertTrue(result.explanation.contains("внешнего IP"))
    }

    @Test fun absentIpv4DoesNotSilentlyPass() {
        val result = VpnRouteAdvisor.assess(true, VpnNetworkFacts(
            visible = true, ipv4DefaultRoute = false,
            ipv6DefaultRoute = true, dnsConfigured = true,
        ))
        assertEquals("vpn_routes_review", result.code)
        assertTrue(result.explanation.contains("IPv4"))
    }
}
