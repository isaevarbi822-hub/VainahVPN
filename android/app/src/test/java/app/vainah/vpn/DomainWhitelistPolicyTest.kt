package app.vainah.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DomainWhitelistPolicyTest {
    @Test fun startsWithNoBypass() {
        assertTrue(DomainWhitelistPolicy.normalize(emptyList()).isEmpty())
        assertTrue(DomainWhitelistPolicy.effective(emptyList(), false).isEmpty())
    }

    @Test fun normalizesUserProvidedDomainNamesWithoutSchemes() {
        assertEquals("example.org", DomainWhitelistPolicy.canonical(" ExAmPlE.OrG "))
        assertEquals("xn--e1afmkfd.xn--p1ai",
            DomainWhitelistPolicy.canonical("пример.рф"))
        assertEquals(
            setOf("example.org", "sub.example.org"),
            DomainWhitelistPolicy.normalize(listOf("SUB.Example.ORG", "example.org"))
        )
    }

    @Test fun invalidAndPotentiallyUnsafeInputsAreNeverRouted() {
        for (value in listOf(
            "", "example", "*.example.org", "https://example.org",
            "example.org/path", "example.org:443", "example..org",
            ".example.org", "example.org.", "example.org#token",
            "example.org?x=1", "example.org\nother.org",
            "127.0.0.1", "[::1]", "localhost", "a_.example.org",
            "-bad.example.org", "exa mple.org",
        )) {
            assertNull("must reject $value", DomainWhitelistPolicy.canonical(value))
        }
        assertTrue(DomainWhitelistPolicy.normalize(listOf(
            "example.org", "https://invalid.example"
        )).isEmpty())
    }

    @Test fun rejectsTooManyDomainsInsteadOfSilentlyDiscardingSome() {
        val domains = (1..21).map { "test$it.example.org" }
        assertTrue(DomainWhitelistPolicy.normalize(domains).isEmpty())
        assertEquals(20, DomainWhitelistPolicy.normalize(domains.take(20)).size)
    }

    @Test fun lockdownOverridesEveryDomainRoutingException() {
        val configured = listOf("mail.example.org", "school.example.org")
        assertEquals(configured.toSet(),
            DomainWhitelistPolicy.effective(configured, lockdownEnabled = false))
        assertTrue(DomainWhitelistPolicy.effective(configured, lockdownEnabled = true)
            .isEmpty())
        assertFalse(DomainWhitelistPolicy.canonical("example.org") == null)
    }
}
