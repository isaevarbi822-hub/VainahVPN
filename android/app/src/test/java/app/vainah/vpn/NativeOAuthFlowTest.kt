package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test
import java.security.MessageDigest
import java.util.Base64

class NativeOAuthFlowTest {
    @Test fun browserNeverReceivesThePkceVerifier() {
        val first = NativeOAuthFlow.verifier()
        val second = NativeOAuthFlow.verifier()
        assertNotEquals(first, second)
        assertEquals(43, first.length)
        val challenge = NativeOAuthFlow.challenge(first)
        assertEquals(43, challenge.length)
        val manual = Base64.getUrlEncoder().withoutPadding().encodeToString(
            MessageDigest.getInstance("SHA-256").digest(first.toByteArray())
        )
        assertEquals(manual, challenge)
        assertNotEquals(first, challenge)
    }

    @Test fun onlyUnexpiredKnownProviderFlowMayBeRedeemed() {
        val now = 1_800_000L
        val good = NativeOAuthFlow.Pending(
            "12345678-1234-4234-8234-123456789012",
            "google", NativeOAuthFlow.verifier(), now - 100_000L
        )
        assertTrue(NativeOAuthFlow.validPending(good, now))
        assertTrue(NativeOAuthFlow.validPending(
            good.copy(provider = "telegram"), now))
        assertFalse(NativeOAuthFlow.validPending(
            good.copy(provider = "other"), now))
        assertFalse(NativeOAuthFlow.validPending(good, now + 600_001L))
        assertFalse(NativeOAuthFlow.validPending(
            good.copy(flow = "12345678-1234-4234-8234-123456789012evil"), now))
        assertFalse(NativeOAuthFlow.validPending(
            good.copy(verifier = "short"), now))
    }

    @Test fun authorizationCodesMustNeverContainUrisOrQueryPayload() {
        assertTrue(NativeOAuthFlow.validCode("A".repeat(43)))
        assertFalse(NativeOAuthFlow.validCode(
            "oauth?session=private-cookie-value"))
        assertFalse(NativeOAuthFlow.validCode("B".repeat(200)))
        assertFalse(NativeOAuthFlow.validFlow(
            "https://attacker.test/redirect"))
    }

    @Test fun unsupportedPkceMaterialIsRejected() {
        assertThrows(IllegalArgumentException::class.java) {
            NativeOAuthFlow.challenge("short")
        }
    }
}
