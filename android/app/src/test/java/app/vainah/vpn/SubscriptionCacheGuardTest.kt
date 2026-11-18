package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class SubscriptionCacheGuardTest {
    private val fake = VainahNode(
        "Турция 1",
        "vless://00000000-0000-4000-8000-000000000001@" +
            "example.org:443?security=tls&type=tcp&sni=example.org"
    )

    @Test fun successfulNonEmptyResponseRemainsEligibleForEncryptedCache() {
        val actual = listOf(fake)
        assertSame(actual, SubscriptionCacheGuard.requireUsable(actual))
    }

    @Test fun emptySuccessfulResponseMustNeverReplacePreviouslyCachedNodes() {
        val previous = listOf(fake)
        val latest = emptyList<VainahNode>()
        val candidate = runCatching { SubscriptionCacheGuard.requireUsable(latest) }
        assertTrue(candidate.exceptionOrNull() is SubscriptionEmptyResult)
        assertEquals(1, previous.size)
        assertEquals("empty_response", SubscriptionLoadFailure.code(candidate.exceptionOrNull()))
        val publicText = SubscriptionLoadFailure.explain(candidate.exceptionOrNull()!!)
        assertTrue(publicText.contains("сохранённый список не удалён"))
        assertFalse(publicText.contains("example.org"))
    }

    @Test fun diagnosticsNeverIncludeSecretErrorStringsOrUnknownCodes() {
        assertEquals("https_timeout", SubscriptionLoadFailure.code(
            SubscriptionRequestTimeout(SubscriptionOrigin.Kind.OTHER_HTTPS)
        ))
        assertEquals("http_403", SubscriptionLoadFailure.code(SubscriptionHttpStatus(403)))
        assertEquals("http_429", SubscriptionLoadFailure.code(SubscriptionHttpStatus(429)))
        assertEquals("none", SubscriptionLoadFailure.safeCode("none"))
        assertEquals("unknown", SubscriptionLoadFailure.safeCode(
            "https://private.example/sub?token=SECRET"
        ))
    }

    @Test fun noImportedNodesMeansTurkeyAvailabilityCannotBeAssessed() {
        val audit = TurkeyServerAudit.inspect(emptyList())
        assertEquals(2, audit.size)
        assertTrue(audit.all { it.status == TurkeyServerAudit.Status.NOT_LOADED })
        assertTrue(audit.all { it.safeDiagnostic == "subscription_not_loaded" })
        val report = VpnDiagnosticReport.create(
            phase = "off", lastStage = null, probeReason = null,
            androidApiLevel = 37, serviceRunning = false,
            subscriptionSource = SubscriptionOrigin.Kind.OTHER_HTTPS,
            subscriptionCachedCount = 0,
            subscriptionRefreshResult = "https_timeout",
            turkeyAudit = audit
        )
        assertTrue(report.contains("subscription_source=other_https"))
        assertTrue(report.contains("subscription_local_nodes=0"))
        assertTrue(report.contains("subscription_refresh_result=https_timeout"))
        assertTrue(report.contains("turkey_1_local_profile=subscription_not_loaded"))
        assertTrue(report.contains("turkey_ip_local_profile=subscription_not_loaded"))
        assertFalse(report.contains("private.example"))
        assertFalse(report.contains("SECRET"))
    }
}
