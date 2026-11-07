package app.vainah.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VpnFailureAdvisorTest {
    @Test fun trustedLibboxStagesMapToFixedCodes() {
        assertEquals("libbox_initialization",
            VpnFailureAdvisor.fromStage("initializing_libbox_setup").code)
        assertEquals("tun_establishment",
            VpnFailureAdvisor.fromStage("opening_android_tun").code)
        assertEquals("config_validation",
            VpnFailureAdvisor.fromStage("validating_libbox_config").code)
        assertEquals("engine_stopped",
            VpnFailureAdvisor.fromStage("native_engine_stopped").code)
    }

    @Test fun nativeStopIsExplainedByStoredCodeEvenAfterLastStageChanged() {
        val original = VpnFailureAdvisor.fromStage("native_engine_stopped")
        val restored = VpnFailureAdvisor.fromCode(original.code)
        assertEquals("engine_stopped", restored.code)
        assertTrue(restored.title.contains("остановился"))
        assertTrue(restored.action.contains("вручную"))
        assertEquals("engine_error", VpnFailureAdvisor.fromCode(
            "vless://user@private.example"
        ).code)
    }

    @Test fun neverIncludesUntrustedNativeExceptionText() {
        val injected = "opening_android_tun vless://uuid@vpn.example.org?pbk=private"
        val warning = VpnFailureAdvisor.fromStage(injected)
        assertEquals("engine_error", warning.code)
        assertFalse(warning.title.contains("private"))
        assertFalse(warning.action.contains("vpn.example.org"))
        assertEquals("unknown", VpnFailureAdvisor.sanitizedCode(injected))
        assertEquals("unknown", VpnFailureAdvisor.sanitizedCode("engine_error\nsecret=1"))
        assertEquals("unknown", VpnFailureAdvisor.sanitizedCode(null))
    }

    @Test fun tellsCustomerToAvoidRepaymentOnUnknownFailure() {
        val warning = VpnFailureAdvisor.fromStage(null)
        assertEquals("engine_error", warning.code)
        assertTrue(warning.action.contains("Не оплачивай"))
    }

    @Test fun onlyAllowlistedCodesMayAppearInSupportReport() {
        val legitimate = VpnDiagnosticReport.create(
            "failed", "initializing_libbox_setup", null, 35, false,
            recoveryCode = "underlay_long_outage",
            failureCode = "libbox_initialization",
        )
        assertTrue(legitimate.contains("underlay_recovery=underlay_long_outage"))
        assertTrue(legitimate.contains("engine_failure=libbox_initialization"))

        val leaked = VpnDiagnosticReport.create(
            "failed", "vless://private", "secret", 35, false,
            recoveryCode = "ssid=secret\nprivate",
            failureCode = "vless://uuid@vpn.example.org",
        )
        assertTrue(leaked.contains("underlay_recovery=unknown"))
        assertTrue(leaked.contains("engine_failure=unknown"))
        assertFalse(leaked.contains("uuid@vpn.example.org"))
        assertFalse(leaked.contains("ssid=secret"))
    }
}
