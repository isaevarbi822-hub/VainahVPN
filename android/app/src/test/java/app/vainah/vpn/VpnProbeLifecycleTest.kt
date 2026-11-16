package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class VpnProbeLifecycleTest {
    @Test fun onlyStillPendingCurrentSelfProbeCanTimeOut() {
        assertTrue(VpnProbeLifecycle.shouldMarkTimedOut(
            true, VpnConnectionState.TUN_READY,
            VpnProbeLifecycle.CHECKING_STAGE, VpnProbeLifecycle.IN_PROGRESS
        ))
        assertFalse(VpnProbeLifecycle.shouldMarkTimedOut(
            false, VpnConnectionState.TUN_READY,
            VpnProbeLifecycle.CHECKING_STAGE, VpnProbeLifecycle.IN_PROGRESS
        ))
        assertFalse(VpnProbeLifecycle.shouldMarkTimedOut(
            true, VpnConnectionState.OFF,
            VpnProbeLifecycle.CHECKING_STAGE, VpnProbeLifecycle.IN_PROGRESS
        ))
        assertFalse(VpnProbeLifecycle.shouldMarkTimedOut(
            true, VpnConnectionState.TUN_READY,
            "vpn_https_probe_success", VpnProbeLifecycle.IN_PROGRESS
        ))
        assertFalse(VpnProbeLifecycle.shouldMarkTimedOut(
            true, VpnConnectionState.TUN_READY,
            VpnProbeLifecycle.CHECKING_STAGE, "https_204"
        ))
    }

    @Test fun timeoutMeansInconclusiveNotConnectionFailure() {
        assertEquals(15_000L, VpnProbeLifecycle.TIMEOUT_MS)
        assertEquals("probe_timeout", VpnProbeLifecycle.TIMEOUT)
        val report = VpnDiagnosticReport.create(
            VpnConnectionState.TUN_READY, VpnProbeLifecycle.TIMEOUT_STAGE,
            VpnProbeLifecycle.TIMEOUT, 37, true
        )
        assertTrue(report.contains("https_probe=probe_timeout"))
        assertTrue(report.contains("vpn_egress=not_verified_on_device"))
        assertEquals("egress_inconclusive",
            VpnFailureAdvisor.fromStage(VpnProbeLifecycle.TIMEOUT_STAGE).code)
    }
}
