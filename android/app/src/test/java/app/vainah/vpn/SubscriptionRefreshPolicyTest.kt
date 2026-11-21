package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class SubscriptionRefreshPolicyTest {
    @Test fun accessDeniedDoesNotTriggerAnAutomaticRetryOnPageReentry() {
        val now = 90_000L
        val blockedUntil = SubscriptionRefreshPolicy.nextAllowed(now, SubscriptionHttpStatus(403))
        assertEquals(30 * 60 * 1000L, blockedUntil - now)
        assertFalse(SubscriptionRefreshPolicy.shouldAutoRefresh(
            now + 10_000L, blockedUntil, runningVpn = false, isDirectKey = false))
        assertTrue(SubscriptionRefreshPolicy.shouldAutoRefresh(
            blockedUntil, blockedUntil, runningVpn = false, isDirectKey = false))
    }

    @Test fun throttle401And429AndTemporaryNetworkErrors() {
        assertEquals(30 * 60 * 1000L,
            SubscriptionRefreshPolicy.retryDelay(SubscriptionHttpStatus(401)))
        assertEquals(15 * 60 * 1000L,
            SubscriptionRefreshPolicy.retryDelay(SubscriptionHttpStatus(429)))
        assertEquals(2 * 60 * 1000L,
            SubscriptionRefreshPolicy.retryDelay(SubscriptionHttpStatus(503)))
        assertEquals(2 * 60 * 1000L,
            SubscriptionRefreshPolicy.retryDelay(IllegalStateException("network")))
        assertEquals(5 * 60 * 1000L, SubscriptionRefreshPolicy.retryDelay(null))
    }

    @Test fun neverAutoRefreshWhileVpnIsRunningOrKeyIsLocal() {
        assertFalse(SubscriptionRefreshPolicy.shouldAutoRefresh(
            100L, 0L, runningVpn = true, isDirectKey = false))
        assertFalse(SubscriptionRefreshPolicy.shouldAutoRefresh(
            100L, 0L, runningVpn = false, isDirectKey = true))
        assertTrue(SubscriptionRefreshPolicy.shouldAutoRefresh(
            100L, 0L, runningVpn = false, isDirectKey = false))
    }
}
