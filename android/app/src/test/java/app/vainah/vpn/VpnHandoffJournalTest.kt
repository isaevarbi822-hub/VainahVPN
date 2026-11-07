package app.vainah.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VpnHandoffJournalTest {
    private fun evt(from: String, to: String, checked: Boolean = true) =
        VpnHandoffEvent(from, to, "underlay_changed", checked)

    @Test fun appendsPhysicalNetworkTransitionsInOrder() {
        var stored: String? = null
        stored = VpnHandoffJournal.append(
            stored, VpnHandoffEvent("none", "wifi", "underlay_available", true)
        )
        stored = VpnHandoffJournal.append(stored, evt("wifi", "cellular"))
        stored = VpnHandoffJournal.append(stored, evt("cellular", "wifi", false))
        val history = VpnHandoffJournal.parse(stored)
        assertEquals(3, history.size)
        assertEquals("wifi", history[1].from)
        assertEquals("cellular", history[1].to)
        assertFalse(history[2].validated)
        assertTrue(VpnHandoffJournal.sanitizedReport(stored)
            .contains("wifi>cellular:underlay_changed:1"))
    }

    @Test fun historyNeverGrowsBeyondTwelveEvents() {
        var stored: String? = ""
        repeat(100) { index ->
            stored = VpnHandoffJournal.append(
                stored,
                if (index % 2 == 0) evt("wifi", "cellular")
                else evt("cellular", "wifi")
            )
        }
        val history = VpnHandoffJournal.parse(stored)
        assertEquals(VpnHandoffJournal.MAX_EVENTS, history.size)
        assertEquals("wifi", history.first().from)
        assertEquals("wifi", history.last().to)
    }

    @Test fun corruptedOrPrivateValuesAreDropped() {
        val malicious = listOf(
            "MyHomeWifi", "192.0.2.2", "vless://secret", "ssid,password",
            "example.com", "cellular\nsecret=private"
        )
        for (secret in malicious) {
            val injected = VpnHandoffEvent(secret, "wifi", "underlay_changed", true)
            assertFalse(VpnHandoffJournal.safe(injected))
            val stored = VpnHandoffJournal.append(null, injected)
            assertEquals(emptyList<VpnHandoffEvent>(), VpnHandoffJournal.parse(stored))
            assertFalse(VpnHandoffJournal.sanitizedReport(stored).contains(secret))
        }
        val malformed = "wifi,cellular,underlay_changed,YES;" +
            "wifi,cellular,underlay_changed,1,private;" +
            "wifi,secret,underlay_changed,1"
        assertTrue(VpnHandoffJournal.parse(malformed).isEmpty())
    }

    @Test fun reportDoesNotLeakInjectedCredentials() {
        val safe = evt("wifi", "cellular")
        val unsafe = evt("vless://token@example.org", "cellular")
        val report = VpnDiagnosticReport.create(
            "tun_ready", "vpn_https_probe_success", "https_204",
            35, true, handoffEvents = listOf(safe, unsafe)
        )
        assertTrue(report.contains("underlay_history=wifi>cellular:underlay_changed:1"))
        assertFalse(report.contains("token@example.org"))
        assertFalse(report.contains("vless://"))
        assertTrue(report.contains("vpn_egress=not_verified_on_device"))
    }

    @Test fun emptyOrUnknownHistoryHasSafeFallback() {
        assertEquals("none", VpnHandoffJournal.sanitizedReport(null))
        assertEquals("none", VpnHandoffJournal.sanitized(emptyList()))
        assertEquals(emptyList<VpnHandoffEvent>(), VpnHandoffJournal.parse(null))
    }
}
