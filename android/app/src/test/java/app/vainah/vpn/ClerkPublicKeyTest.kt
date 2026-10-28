package app.vainah.vpn

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.charset.StandardCharsets
import java.util.Base64

class ClerkPublicKeyTest {
    private fun publicKey(host: String): String {
        val payload = Base64.getUrlEncoder().withoutPadding()
            .encodeToString((host + "$").toByteArray(StandardCharsets.US_ASCII))
        return "pk_test_" + payload
    }

    @Test fun rejectsSyntheticAndSecretKeys() {
        assertFalse(ClerkPublicKey.isConfigured(""))
        assertFalse(ClerkPublicKey.isConfigured("pk_test_synthetic_ci_only_not_a_real_instance"))
        assertFalse(ClerkPublicKey.isConfigured("sk_live_something"))
        assertFalse(ClerkPublicKey.isConfigured("pk_test_broken"))
    }

    @Test fun acceptsRealFormatPublishableKeys() {
        assertTrue(ClerkPublicKey.isConfigured(publicKey("example.clerk.accounts.dev")))
        assertFalse(ClerkPublicKey.isConfigured(publicKey("invalid")))
        assertFalse(ClerkPublicKey.isConfigured(publicKey("invalid..example.com")))
    }
}
