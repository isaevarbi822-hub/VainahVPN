package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class CabinetNavigationTest {
    @Test fun onlyExactOfficialHttpsPagesMayOpenInCabinet() {
        for ((label, page) in CabinetNavigation.sections()) {
            assertTrue(label.isNotBlank())
            val url = CabinetNavigation.url(page)
            assertNotNull(url)
            assertTrue(CabinetNavigation.isTrustedUrl(url!!))
            assertTrue(url.startsWith("https://vainahvpn.onrender.com/"))
        }
        assertEquals("https://vainahvpn.onrender.com/account.html",
            CabinetNavigation.url("account.html"))
    }

    @Test fun rejectsExternalHostsProtocolDowngradeAndBearerUrls() {
        val bad = listOf(
            "https://evil.example.org/account.html",
            "http://vainahvpn.onrender.com/account.html",
            "https://vainahvpn.onrender.com.evil.org/account.html",
            "https://user:pass@vainahvpn.onrender.com/account.html",
            "https://vainahvpn.onrender.com:444/account.html",
            "https://vainahvpn.onrender.com/account.html?token=private",
            "https://vainahvpn.onrender.com/account.html#session",
            "javascript:alert(1)"
        )
        assertTrue(bad.none(CabinetNavigation::isTrustedUrl))
        assertNull(CabinetNavigation.url("https://evil.example.org/account.html"))
        assertNull(CabinetNavigation.url("../admin"))
        assertNull(CabinetNavigation.url("checkout.html"))
    }
}
