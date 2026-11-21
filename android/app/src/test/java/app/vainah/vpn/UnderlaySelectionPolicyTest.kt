package app.vainah.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class UnderlaySelectionPolicyTest {
    private fun wifi(key: String = "wifi1", validated: Boolean = true) =
        UnderlayCandidate(key, validated, unmetered = true, transport = "wifi")

    private fun cell(key: String = "cell1", validated: Boolean = true) =
        UnderlayCandidate(key, validated, unmetered = false, transport = "cellular")

    @Test fun keepsCurrentValidatedWifiWhenCellularAppears() {
        val selected = UnderlaySelectionPolicy.choose("wifi1",
            listOf(cell(), wifi()))
        assertEquals("wifi1", selected?.key)
        assertEquals("underlay_unchanged",
            UnderlaySelectionPolicy.transition("wifi1", selected?.key))
    }

    @Test fun changesToValidatedMobileWhenWifiIsNoLongerValidated() {
        val selected = UnderlaySelectionPolicy.choose("wifi1",
            listOf(wifi(validated = false), cell(validated = true)))
        assertEquals("cell1", selected?.key)
        assertEquals("underlay_changed",
            UnderlaySelectionPolicy.transition("wifi1", selected?.key))
        // When Wi-Fi later recovers, retain an already working mobile link.
        assertEquals("cell1", UnderlaySelectionPolicy.choose("cell1",
            listOf(wifi(validated = true), cell(validated = true)))?.key)
    }

    @Test fun selectsWifiWhenNewSessionSeesBothValidatedNetworks() {
        assertEquals("wifi1", UnderlaySelectionPolicy.choose(
            null, listOf(cell(), wifi()))?.key)
        assertEquals("wifi1", UnderlaySelectionPolicy.choose(
            null, listOf(wifi(), cell()))?.key)
    }

    @Test fun refusesToCallUnvalidatedInternetAvailableVerified() {
        assertEquals("wifi1", UnderlaySelectionPolicy.choose(
            "wifi1", listOf(wifi(validated = false), cell(validated = false)))?.key)
        assertEquals("cell1", UnderlaySelectionPolicy.choose(
            "wifi1", listOf(cell(validated = false)))?.key)
        assertNull(UnderlaySelectionPolicy.choose("wifi1", emptyList()))
        assertEquals("underlay_lost",
            UnderlaySelectionPolicy.transition("wifi1", null))
        assertEquals("underlay_available",
            UnderlaySelectionPolicy.transition(null, "wifi1"))
    }

    @Test fun rejectsMalformedNetworkCandidatesAndStaysDeterministic() {
        assertNull(UnderlaySelectionPolicy.choose(null, listOf(
            UnderlayCandidate("", true, true, "wifi"),
            UnderlayCandidate("vpn", true, true, "vpn")
        )))
        assertEquals("a", UnderlaySelectionPolicy.choose(null, listOf(
            wifi("z"), wifi("a")
        ))?.key)
        assertEquals("eth", UnderlaySelectionPolicy.choose(null, listOf(
            wifi(), UnderlayCandidate("eth", true, true, "ethernet")
        ))?.key)
    }

    @Test fun neverTreatsHandoffAsTunnelValidation() {
        assertEquals("no_underlay",
            UnderlaySelectionPolicy.transition(null, null))
        val r = UnderlaySelectionPolicy.choose(
            "cell1", listOf(cell(validated = false))
        )
        assertEquals(false, r?.validated)
    }
}
