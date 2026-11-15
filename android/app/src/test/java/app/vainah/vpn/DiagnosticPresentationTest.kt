package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

/** Prevent stale HTTP warnings and simulated VPN state in UI. */
class DiagnosticPresentationTest {
    @Test fun healthySubscriptionNeverInventsHttp403() {
        val state = DiagnosticPresentation.subscription(
            hasProfile = true, cachedNodeCount = 41,
            fetching = false, lastError = null
        )
        assertFalse(state.warning)
        assertTrue(state.headline.contains("загружен"))
        assertFalse((state.headline + state.explanation).contains("403"))
        assertFalse(state.secondary.contains("Актуально"))
    }

    @Test fun actualHttp403IsExplainedButDoesNotDisableExistingCachedNodes() {
        val state = DiagnosticPresentation.subscription(
            true, 41, false,
            "HTTP 403: сервер подписки отклонил запрос. Подписка может работать."
        )
        assertTrue(state.warning)
        assertTrue(state.headline.contains("403"))
        assertTrue(state.secondary.contains("41"))
        assertTrue(state.explanation.contains("не означает"))
    }

    @Test fun unrelatedServerErrorIsNotMisidentifiedAs403() {
        val state = DiagnosticPresentation.subscription(
            true, 41, false, "Ошибка DNS: домен подписки не определяется."
        )
        assertTrue(state.warning)
        assertFalse(state.headline.contains("403"))
        assertTrue(state.secondary.contains("41"))
    }

    @Test fun missingProfileAndRefreshHaveDistinctMessages() {
        assertTrue(DiagnosticPresentation.subscription(
            false, 0, false, null
        ).headline.contains("не добавлена"))
        assertTrue(DiagnosticPresentation.subscription(
            true, 13, true, null
        ).headline.contains("Обновляем"))
    }

    @Test fun vpnStatusIsNeverInferredFromWifiAlone() {
        assertEquals("VPN сейчас не запущен",
            DiagnosticPresentation.tunnelHeadline(VpnConnectionState.OFF, false))
        assertEquals("VPN подключается",
            DiagnosticPresentation.tunnelHeadline(VpnConnectionState.STARTING, true))
        assertTrue(DiagnosticPresentation.tunnelHeadline(
            VpnConnectionState.TUN_READY, true).contains("IP не проверен"))
        assertTrue(DiagnosticPresentation.tunnelHeadline(
            VpnConnectionState.TUN_READY, false).contains("не запущен"))
        assertTrue(DiagnosticPresentation.tunnelHeadline(
            VpnConnectionState.FAILED, true).contains("ошибка"))
    }
}
