package app.vainah.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class VpnRecoveryAdvisorTest {
    private fun state(
        transport: String = "wifi", validated: Boolean = true,
        offline: Long? = null, lastOutage: Long? = null, vpn: Boolean = true
    ) = VpnRecoveryState(vpn, transport, validated, offline, lastOutage)

    @Test fun noActiveVpnDoesNotReportCurrentTunnelRecovery() {
        val r = VpnRecoveryAdvisor.advice(
            state("none", false, offline = 90_000L, vpn = false)
        )
        assertEquals("vpn_off", r.code)
        assertFalse(r.attention)
    }

    @Test fun shortLossNeverTriggersAutomaticReconnect() {
        val r = VpnRecoveryAdvisor.advice(state("none", false, offline = 29_999L))
        assertEquals("underlay_brief_outage", r.code)
        assertFalse(r.attention)
        assertTrue(r.message.contains("Не перезапускай VPN"))
    }

    @Test fun prolongedLossRecommendsPhysicalNetworkCheck() {
        val r = VpnRecoveryAdvisor.advice(state("none", false, offline = 30_000L))
        assertEquals("underlay_long_outage", r.code)
        assertTrue(r.attention)
        assertTrue(r.message.contains("Wi-Fi"))
        assertTrue(r.message.contains("Не оплачивай VPN повторно"))
    }

    @Test fun restoredButUnvalidatedNetworkIsNotVpnProof() {
        val r = VpnRecoveryAdvisor.advice(
            state("cellular", false, lastOutage = 120_000L)
        )
        assertEquals("underlay_unvalidated", r.code)
        assertTrue(r.message.contains("не доказательство"))
        assertFalse(r.attention)
    }

    @Test fun longOutageRecoveryRequiresManualVerification() {
        val r = VpnRecoveryAdvisor.advice(
            state("wifi", true, lastOutage = 120_000L)
        )
        assertEquals("underlay_restored_after_outage", r.code)
        assertTrue(r.message.contains("вручную"))
        assertTrue(r.message.contains("не подтверждает"))
        assertEquals("underlay_available", VpnRecoveryAdvisor.advice(
            state("wifi", true, lastOutage = 2_000L)
        ).code)
    }

    @Test fun rebootOrCorruptElapsedTimestampIsRejected() {
        assertNull(VpnRecoveryAdvisor.ageSince(20, 30))
        assertNull(VpnRecoveryAdvisor.ageSince(1_000, -1))
        assertNull(VpnRecoveryAdvisor.ageSince(100, 0))
        assertEquals(29_999L, VpnRecoveryAdvisor.ageSince(50_000, 20_001))
        assertNull(VpnRecoveryAdvisor.ageSince(86_400_002, 1))
    }
}
