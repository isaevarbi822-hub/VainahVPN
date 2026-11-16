package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class VpnStartupPreflightTest {
    @Test fun aBadProfileIsNotMisreportedAsExpiredSubscription() {
        val stage = VpnStartupPreflight.failureStage(true, true, false)
        assertEquals("validating_selected_profile", stage)
        val advice = VpnFailureAdvisor.fromStage(stage)
        assertEquals("profile_invalid", advice.code)
        assertFalse(advice.action.contains("Обнови подписку"))
    }

    @Test fun encryptedSubscriptionAndMissingEngineHaveDistinctErrors() {
        assertEquals("subscription_storage_unavailable",
            VpnStartupPreflight.failureStage(true, false, true))
        assertEquals("engine_unavailable",
            VpnStartupPreflight.failureStage(false, true, true))
        assertNull(VpnStartupPreflight.failureStage(true, true, true))
    }

    @Test fun nativeTransportErrorDoesNotDemandSubscriptionRefresh() {
        val config = VpnFailureAdvisor.fromStage("validating_libbox_config")
        assertEquals("config_validation", config.code)
        assertTrue(config.action.contains("Подписка может быть действующей"))
        assertFalse(config.action.contains("Обнови подписку"))
        assertEquals("transport_startup",
            VpnFailureAdvisor.fromStage("loading_libbox_service").code)
        assertEquals("unknown", VpnFailureAdvisor.sanitizedCode(
            "vless://private@server.example:443"))
    }
}
