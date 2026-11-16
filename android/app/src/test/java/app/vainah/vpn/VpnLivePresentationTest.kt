package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class VpnLivePresentationTest {
    @Test fun serviceStateDoesNotClaimVerifiedInternetEgress() {
        assertEquals("Туннель запущен", VpnLivePresentation.phaseLabel(VpnConnectionState.ONLINE))
        assertEquals("Туннель открыт · интернет не проверен",
            VpnLivePresentation.phaseLabel(VpnConnectionState.TUN_READY))

        assertEquals("Не подключено", VpnLivePresentation.phaseLabel("unknown"))
        assertEquals("Подключение…", VpnLivePresentation.phaseLabel(VpnConnectionState.STARTING))
    }

    @Test fun physicalNetworkValidationIsNotVpnProof() {
        assertEquals("Физическая сеть: Wi-Fi · Android: подтверждена",
            VpnLivePresentation.networkStatus("wifi", true))
        assertEquals("Физическая сеть: 4G / 5G · Android: не подтверждена",
            VpnLivePresentation.networkStatus("cellular", false))
        assertFalse(VpnLivePresentation.networkStatus("wifi", true).contains("VPN защищён"))
    }

    @Test fun disconnectedAndStaleTrafficNeverShowMadeUpNumbers() {
        val sample = VpnTrafficStore.Sample(1200, 2300, 5400, 7600)
        assertFalse(VpnLivePresentation.trafficText(false, true, sample).contains("1200"))
        assertEquals("Счётчики libbox временно недоступны.",
            VpnLivePresentation.trafficText(true, true, null))
        val live = VpnLivePresentation.trafficText(true, true, sample)
        assertTrue(live.contains("Мбит/с"))
        assertTrue(live.contains("За сеанс:"))
        assertTrue(live.contains("\n"))
        assertFalse(VpnLivePresentation.trafficText(true, false, sample).contains("Мбит/с"))
    }
}
