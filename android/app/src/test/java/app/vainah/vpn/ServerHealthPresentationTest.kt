package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class ServerHealthPresentationTest {
    private val reality = SubscriptionNodeSupport.Details("tcp", "reality", true)

    @Test fun measuredTcpDoesNotClaimVpnOr100MbpsSpeed() {
        val result = ServerHealthPresentation.assess(
            reality, ServerTcpObservation(0, 3, listOf(49, 51, 50)))
        assertEquals("TCP 3/3 · 50 мс", result.summary)
        assertTrue(result.explanation.contains("не подтверждает"))
        assertFalse(result.summary.contains("100"))
    }

    @Test fun failedTurkeyPortNeverBecomesFakeLatency() {
        val result = ServerHealthPresentation.assess(
            reality, ServerTcpObservation(1, 3, emptyList()))
        assertEquals("TCP 0/3 · нет надёжного замера", result.summary)
        assertTrue(result.explanation.contains("не ответил"))
    }

    @Test fun cancelledOrDnsStalledProbeCannotBeCalledOffline() {
        val timedOut = ServerHealthPresentation.assess(
            reality, null, interrupted = true)
        assertEquals("TCP: проверка не завершена", timedOut.summary)
        assertTrue(timedOut.explanation.contains("не означает"))
        assertFalse(timedOut.summary.contains("0/3"))
    }

    @Test fun unsupportedTransportAndUnmeasuredNodesAreExplicit() {
        val blocked = ServerHealthPresentation.assess(
            SubscriptionNodeSupport.Details("xhttp", "reality", false), null)
        assertEquals("Транспорт недоступен в этой APK", blocked.summary)
        assertEquals("TCP ещё не проверен",
            ServerHealthPresentation.assess(reality, null).summary)
        assertEquals("Профиль не распознан",
            ServerHealthPresentation.assess(null, null).summary)
    }
}
