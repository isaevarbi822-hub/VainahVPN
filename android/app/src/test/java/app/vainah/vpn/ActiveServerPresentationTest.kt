package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class ActiveServerPresentationTest {
    @Test fun selectedTurkeyProfileMustNeverReplaceRealActiveLabel() {
        assertEquals("Сейчас: Турция · 2",
            ActiveServerPresentation.homeLabel(
                VpnConnectionState.TUN_READY, true,
                "Турция · 2", "Турция · IP"))
        assertEquals("Выбран: Турция · IP",
            ActiveServerPresentation.homeLabel(
                VpnConnectionState.OFF, false,
                "Турция · 2", "Турция · IP"))
    }

    @Test fun cannotSwitchRunningTunnelByOnlyChoosingAListRow() {
        for (phase in listOf(
            VpnConnectionState.STARTING,
            VpnConnectionState.TUN_READY,
            VpnConnectionState.ONLINE
        )) assertTrue(ActiveServerPresentation.requiresDisconnectBeforeSwitch(phase))
        for (phase in listOf(VpnConnectionState.OFF, VpnConnectionState.FAILED))
            assertFalse(ActiveServerPresentation.requiresDisconnectBeforeSwitch(phase))
    }

    @Test fun sensitiveServerLabelsAreNeverShownInShortcut() {
        val leak = ActiveServerPresentation.homeLabel(
            VpnConnectionState.TUN_READY, true,
            "vless://secret@hidden.example:443?token=abc", "Турция · 1")
        assertEquals("Сейчас: VPN-сервер", leak)
        assertFalse(leak.contains("secret"))
        assertEquals("Выбери сервер",
            ActiveServerPresentation.homeLabel(VpnConnectionState.OFF,
                false, null, null))
    }
}
