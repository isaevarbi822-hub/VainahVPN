package app.vainah.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SubscriptionLinkTest {
    @Test fun secureSubscriptionIsAccepted() {
        val url = "https://vpn.example/sub/abcdef?token=private"
        assertEquals(url, SubscriptionLink.validate("  $url  "))
    }
    @Test fun rejectsNonHttpsAndCredentialLeaks() {
        val bad = listOf(
            "http://vpn.example/sub",
            "vless://id@vpn.example:443",
            "https://user:pass@vpn.example/sub",
            "https://vpn.example/sub#fragment",
            "javascript:alert(1)",
            "https://vpn.example/sub\nInjected",
            "https://vpn..example/sub"
        )
        for (value in bad) assertNull(value, SubscriptionLink.validate(value))
    }
}
