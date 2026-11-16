package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class VpnHomeStatusPresentationTest {
    @Test fun openingTunNeverClaimsWorkingInternetOrProtectedIp() {
        val phase = VpnConnectionState.TUN_READY
        assertEquals("Туннель запущен", VpnHomeStatusPresentation.heading(phase))
        assertTrue(VpnHomeStatusPresentation.detail(phase, "probe pending")
            .contains("не подтверждён"))
        assertTrue(VpnHomeStatusPresentation.detail(
            phase, "Проверка интернета не прошла").contains("не прошла"))
    }

    @Test fun actualErrorAndShutdownStayDistinctFromSuccessfulTunnel() {
        assertEquals("Ошибка VPN",
            VpnHomeStatusPresentation.heading(VpnConnectionState.FAILED))
        assertEquals("VPN отключён",
            VpnHomeStatusPresentation.heading(VpnConnectionState.OFF))
        assertEquals("Подключаем VPN…",
            VpnHomeStatusPresentation.heading(VpnConnectionState.STARTING))
    }

    @Test fun networkValidationIsExplicitlyPhysicalOnly() {
        assertEquals("Wi-Fi · Android: физическая сеть проверена",
            VpnHomeStatusPresentation.physicalNetwork("wifi", true))
        assertEquals("4G / 5G · Android: сеть не подтверждена",
            VpnHomeStatusPresentation.physicalNetwork("cellular", false))
        assertFalse(VpnHomeStatusPresentation.physicalNetwork("wifi", true)
            .contains("VPN защищён"))
    }
}
