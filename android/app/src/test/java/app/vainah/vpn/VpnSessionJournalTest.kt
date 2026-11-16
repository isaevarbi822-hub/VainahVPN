package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class VpnSessionJournalTest {
    @Test fun onlyRealPhaseTransitionsCanBeRecorded() {
        assertTrue(VpnSessionJournal.shouldRecord(
            VpnConnectionState.OFF, VpnConnectionState.STARTING))
        assertTrue(VpnSessionJournal.shouldRecord(
            VpnConnectionState.STARTING, VpnConnectionState.TUN_READY))
        assertTrue(VpnSessionJournal.shouldRecord(
            VpnConnectionState.TUN_READY, VpnConnectionState.FAILED))
        assertFalse(VpnSessionJournal.shouldRecord(
            VpnConnectionState.TUN_READY, VpnConnectionState.TUN_READY))
        assertFalse(VpnSessionJournal.shouldRecord(
            VpnConnectionState.OFF, "user-secret-or-vless-url"))
    }

    @Test fun labelsNeverContainSensitiveServerOrProfileMetadata() {
        for (phase in listOf(
            VpnConnectionState.STARTING, VpnConnectionState.TUN_READY,
            VpnConnectionState.FAILED, VpnConnectionState.OFF
        )) {
            val summary = VpnSessionJournal.title(phase)
            assertTrue(summary.isNotBlank())
            assertFalse(summary.contains("vless://"))
            assertFalse(summary.contains("password", true))
        }
    }
}
