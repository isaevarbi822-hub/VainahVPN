package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class SelectedServerTcpAdviceTest {
    @Test fun failedTurkeyEndpointsAreNotMarkedWorking() {
        val failed = SelectedServerTcpAdvice.summary(
            ServerTcpObservation(1, 3, emptyList()))
        assertTrue(failed.contains("не отвечает"))
        assertTrue(failed.contains("0 из 3"))
        assertFalse(failed.contains("REALITY проверен"))
    }

    @Test fun respondingTcpCannotClaimSuccessfulRealityOrBandwidth() {
        val message = SelectedServerTcpAdvice.summary(
            ServerTcpObservation(2, 3, listOf(70, 74, 72)))
        assertTrue(message.contains("TCP-вход доступен"))
        assertTrue(message.contains("72 мс"))
        assertTrue(message.contains("REALITY"))
        assertTrue(message.contains("не проверены"))
    }

    @Test fun partialSuccessAndInvalidSampleCountAreDistinct() {
        assertTrue(SelectedServerTcpAdvice.summary(
            ServerTcpObservation(2, 3, listOf(250))).contains("нестабильно"))
        assertTrue(SelectedServerTcpAdvice.summary(
            ServerTcpObservation(2, 3, listOf(1, 1, 1, 1))).contains("недостоверен"))
    }
}
