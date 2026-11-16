package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class TrafficTimelineTest {
    @Test fun refusesFakedOrInvalidMeasurements() {
        val data = TrafficTimeline(4)
        assertFalse(data.record(-1, 200, 300))
        assertFalse(data.record(1, -1, 300))
        assertFalse(data.record(1, 200, -300))
        assertEquals(0, data.size())
    }

    @Test fun onlyRealMeasurementsAreShownAndRingIsBounded() {
        val data = TrafficTimeline(3)
        assertTrue(data.record(1000, 50, 50))
        assertFalse(data.record(1000, 999, 999))
        assertFalse(data.record(900, 999, 999))
        assertTrue(data.record(3000, 200, 300))
        assertTrue(data.record(5000, 50, 10))
        assertTrue(data.record(7000, 40, 100))
        assertEquals(3, data.size())
        assertEquals(500L, data.peakBytesPerSecond())
        assertEquals(3000L, data.snapshot().first().elapsedMs)
    }

    @Test fun oldSamplesDoNotAppearFreshAfterInterruption() {
        val data = TrafficTimeline()
        data.record(1000, 10, 20)
        data.record(21000, 20, 30)
        assertEquals(1, data.size())
        data.clear()
        assertEquals(emptyList<TrafficTimeline.Point>(), data.snapshot())
        assertNull(data.last())
    }

    @Test fun uptimeAndDeviceWifiNeverProveVpnEgress() {
        assertEquals(ConnectionQuality.Stage.OFF,
            ConnectionQuality.stage(VpnConnectionState.OFF, false))
        assertEquals(ConnectionQuality.Stage.OFF,
            ConnectionQuality.stage(VpnConnectionState.ONLINE, false))
        assertEquals(ConnectionQuality.Stage.STARTING,
            ConnectionQuality.stage(VpnConnectionState.STARTING, true))
        assertEquals(ConnectionQuality.Stage.TUN_CREATED,
            ConnectionQuality.stage(VpnConnectionState.TUN_READY, true))
        assertEquals(ConnectionQuality.Stage.FAILURE,
            ConnectionQuality.stage(VpnConnectionState.FAILED, false))
        assertTrue(ConnectionQuality.text(ConnectionQuality.Stage.TUN_CREATED)
            .contains("IP не проверен"))
    }
}
