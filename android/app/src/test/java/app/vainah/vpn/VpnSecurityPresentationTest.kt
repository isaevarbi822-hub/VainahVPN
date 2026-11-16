package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class VpnSecurityPresentationTest {
    @Test fun startupDoesNotClaimConnectedTunnel() {
        val s = VpnSecurityPresentation.tunnel(VpnConnectionState.STARTING, true)
        assertEquals("Подключается", s.title)
        assertEquals(VainahUi.Tone.PURPLE, s.tone)
        assertFalse(s.title.contains("создан"))
    }

    @Test fun activeTunNeverProvesExitIpOrEncryptedEgress() {
        for (phase in listOf(VpnConnectionState.TUN_READY, VpnConnectionState.ONLINE)) {
            val status = VpnSecurityPresentation.tunnel(phase, true)
            assertTrue(status.title.contains("не проверен"))
            assertNotEquals(VainahUi.Tone.SUCCESS, status.tone)
        }
    }

    @Test fun staleVpnStateCannotClaimRunningAfterServiceStop() {
        for (phase in listOf(VpnConnectionState.ONLINE, VpnConnectionState.STARTING)) {
            assertEquals("Служба не запущена",
                VpnSecurityPresentation.tunnel(phase, false).title)
        }
        assertEquals("Ошибка подключения",
            VpnSecurityPresentation.tunnel(VpnConnectionState.FAILED, true).title)
    }
}
