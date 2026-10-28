package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class VpnDiagnosticReportTest {
    @Test fun includesOnlyCredentialsFreeCodes() {
        val report = VpnDiagnosticReport.create(
            "tun_ready", "vpn_https_probe_inconclusive",
            "dns_resolution_failed", 35, true
        )
        assertTrue(report.contains("android_api=35"))
        assertTrue(report.contains("phase=tun_ready"))
        assertTrue(report.contains("https_probe=dns_resolution_failed"))
        assertTrue(report.contains("vpn_egress=not_verified_on_device"))
    }

    @Test fun successfulAppHttpsProbeCanBeReportedWithoutEgressClaim() {
        val report = VpnDiagnosticReport.create(
            "online", "vpn_https_probe_success", "https_204", 37, true
        )
        assertTrue(report.contains("phase=online"))
        assertTrue(report.contains("https_probe=https_204"))
        assertTrue(report.contains("vpn_egress=not_verified_on_device"))
        assertFalse(report.contains("vpn_egress=verified"))
    }

    @Test fun deviceRouteFactsAreExplicitlyUnknownWhenUnobservable() {
        val report = VpnDiagnosticReport.create(
            "tun_ready", "vpn_https_probe_inconclusive", "https_timeout", 37,
            true, VpnNetworkFacts(visible = true)
        )
        assertTrue(report.contains("android_vpn_visible=yes"))
        assertTrue(report.contains("android_ipv4_default_route=unknown"))
        assertTrue(report.contains("android_ipv6_default_route=unknown"))
        assertTrue(report.contains("android_vpn_dns_configured=unknown"))
    }

    @Test fun missingRoutesCanBeReportedWithoutLeakingAddresses() {
        val report = VpnDiagnosticReport.create(
            "tun_ready", "vpn_https_probe_inconclusive", "dns_resolution_failed", 37,
            true, VpnNetworkFacts(
                visible = true, ipv4DefaultRoute = false, ipv6DefaultRoute = true,
                dnsConfigured = false
            )
        )
        assertTrue(report.contains("android_ipv4_default_route=no"))
        assertTrue(report.contains("android_ipv6_default_route=yes"))
        assertTrue(report.contains("android_vpn_dns_configured=no"))
        assertFalse(report.contains("172.19.0.2"))
        assertTrue(report.contains("vpn_egress=not_verified_on_device"))
    }

    @Test fun maliciousValuesCannotLeakIntoClipboard() {
        val privateUrl = "https://example.org/?token=really_private"
        val profile = "vless://secret-uuid@host.example:443"
        val report = VpnDiagnosticReport.create(
            privateUrl, profile, "dns_failed\nSecret=abc", 123456, false
        )
        assertFalse(report.contains("really_private"))
        assertFalse(report.contains("secret-uuid"))
        assertFalse(report.contains("Secret=abc"))
        assertTrue(report.contains("phase=unknown"))
        assertTrue(report.contains("last_stage=unknown"))
        assertTrue(report.contains("https_probe=unknown"))
        assertTrue(report.contains("android_api=unknown"))
        assertTrue(report.contains("service_running=no"))
    }
}
