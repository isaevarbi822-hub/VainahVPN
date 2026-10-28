package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class VpnTrafficStoreTest {
    @Test fun byteCountsUseBinaryUnitsAndNeverInventValues() {
        assertEquals("0 Б", VpnTrafficStore.format(0))
        assertEquals("1023 Б", VpnTrafficStore.format(1023))
        assertEquals("1.0 КиБ", VpnTrafficStore.format(1024))
        assertEquals("2.0 МиБ", VpnTrafficStore.format(2L * 1024 * 1024))
        assertEquals("—", VpnTrafficStore.format(-1))
    }

    @Test fun sampleKeepsSeparateRatesAndSessionTotals() {
        val sample = VpnTrafficStore.Sample(1024L, 2048L, 123456L, 654321L)
        assertEquals(1024L, sample.uplink)
        assertEquals(2048L, sample.downlink)
        assertTrue(sample.uplinkTotal > sample.uplink)
        assertTrue(sample.downlinkTotal > sample.downlink)
    }
}
