package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

/** Offline IP arithmetic contract tests. No network, profile or credential. */
class TunDnsFallbackTest {
    @Test fun derivesVirtualIpv4Address() {
        assertEquals("172.19.0.2", TunDnsFallback.nextAddress("172.19.0.1", 30))
        assertEquals("10.0.0.1", TunDnsFallback.nextAddress("10.0.0.0", 24))
        assertEquals("172.19.1.0", TunDnsFallback.nextAddress("172.19.0.255", 16))
    }

    @Test fun derivesVirtualIpv6Address() {
        val value = TunDnsFallback.nextAddress("fd00:19::1", 126)
        assertNotNull(value)
        assertArrayEquals(
            java.net.InetAddress.getByName("fd00:19::2").address,
            java.net.InetAddress.getByName(value).address
        )
    }

    @Test fun refusesOutOfPrefixDnsOrInvalidInput() {
        assertNull(TunDnsFallback.nextAddress("172.19.0.3", 30))
        assertNull(TunDnsFallback.nextAddress("192.0.2.1", 32))
        assertNull(TunDnsFallback.nextAddress("255.255.255.255", 0))
        assertNull(TunDnsFallback.nextAddress("example.org", 24))
        assertNull(TunDnsFallback.nextAddress("172.19.0.1", 33))
        assertNull(TunDnsFallback.nextAddress("fd00:19::3", 126))
    }
}
