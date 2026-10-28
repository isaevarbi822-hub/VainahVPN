package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class TcpLatencyTest {
    @Test fun medianRejectsOutlierAndIgnoresArrivalOrder() {
        assertEquals(47, TcpLatency.median(listOf(900, 47, 39)))
        assertEquals(47, TcpLatency.median(listOf(39, 900, 47)))
    }

    @Test fun oneOrTwoSuccessfulConnectionsStillGiveRealMeasurement() {
        assertEquals(35, TcpLatency.median(listOf(35)))
        assertEquals(50, TcpLatency.median(listOf(40, 60)))
    }

    @Test fun invalidSamplesNeverBecomeFakePing() {
        assertNull(TcpLatency.median(emptyList()))
        assertNull(TcpLatency.median(listOf(-1, 60001)))
        assertEquals(5, TcpLatency.median(listOf(-1, 5, 90000)))
    }
}
