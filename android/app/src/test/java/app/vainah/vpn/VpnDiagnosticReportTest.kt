package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class VpnDiagnosticReportTest {
    @Test fun localProfileRejectionIsReportedEvenWithVpnOff() {
        val report = VpnDiagnosticReport.create("off", null, null, 37, false,
            selectedTransport = "tcp", selectedSecurity = "reality",
            profileCheckTransport = "xhttp", profileCheckSecurity = "tls",
            profileCheckRejection = "xhttp_xmux_invalid_type")
        assertTrue(report.contains("app_version=${BuildConfig.VERSION_NAME}"))
        assertTrue(report.contains("app_version_code=${BuildConfig.VERSION_CODE}"))
        assertTrue(report.contains("selected_transport=tcp"))
        assertTrue(report.contains("selected_security=reality"))
        assertTrue(report.contains("last_profile_check_transport=xhttp"))
        assertTrue(report.contains("last_profile_check_security=tls"))
        assertTrue(report.contains("last_profile_check_result=xhttp_xmux_invalid_type"))
    }

    @Test fun profileCheckFieldsNeverExportUserValues() {
        val report = VpnDiagnosticReport.create("off", null, null, 37, false,
            profileCheckTransport = "private_host", profileCheckSecurity = "private_token",
            profileCheckRejection = "private_uuid")
        assertTrue(report.contains("last_profile_check_result=unknown"))
        assertFalse(report.contains("private_"))
    }

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

    @Test fun reportsUnderlayHandoffWithoutWifiNamesOrVpnCredentials() {
        val report = VpnDiagnosticReport.create(
            "tun_ready", "vpn_https_probe_success", "https_204", 35, true,
            underlay = VpnUnderlayFacts(
                transport = "cellular", validated = true, transitions = 2
            )
        )
        assertTrue(report.contains("underlay_type=cellular"))
        assertTrue(report.contains("underlay_validated=yes"))
        assertTrue(report.contains("underlay_switches=2"))
        assertTrue(report.contains("vpn_egress=not_verified_on_device"))
        assertFalse(report.contains("wifi-ssid"))
        assertFalse(report.contains("vless://"))
        assertFalse(report.contains("underlay_ip="))
    }

    @Test fun sanitizesMaliciousOrUnboundedHandoffFacts() {
        val report = VpnDiagnosticReport.create(
            "tun_ready", null, null, 35, true,
            underlay = VpnUnderlayFacts(
                transport = "wifi\\nsecret=vless://private", validated = false,
                transitions = 9999999
            )
        )
        assertTrue(report.contains("underlay_type=unknown"))
        assertTrue(report.contains("underlay_validated=no"))
        assertTrue(report.contains("underlay_switches=unknown"))
        assertFalse(report.contains("secret="))
        assertFalse(report.contains("vless://private"))
    }

    @Test fun reportDistinguishesUnperformedRouteScanFromUnobservableFacts() {
        val notRun = VpnDiagnosticReport.create(
            "tun_ready", VpnProbeLifecycle.CHECKING_STAGE,
            VpnProbeLifecycle.IN_PROGRESS, 37, true
        )
        assertTrue(notRun.contains("https_probe=in_progress"))
        assertTrue(notRun.contains("vpn_route_check=not_run"))
        assertTrue(notRun.contains("android_vpn_visible=unknown"))

        val checked = VpnDiagnosticReport.create(
            "tun_ready", VpnProbeLifecycle.TIMEOUT_STAGE,
            VpnProbeLifecycle.TIMEOUT, 37, true,
            VpnNetworkFacts(visible = null)
        )
        assertTrue(checked.contains("vpn_route_check=completed"))
        assertTrue(checked.contains("android_vpn_visible=unknown"))
        assertTrue(checked.contains("https_probe=probe_timeout"))

        val pending = VpnDiagnosticReport.create(
            "tun_ready", VpnProbeLifecycle.CHECKING_STAGE,
            VpnProbeLifecycle.IN_PROGRESS, 37, true,
            routeScanPending = true
        )
        assertTrue(pending.contains("vpn_route_check=in_progress"))
        assertTrue(pending.contains("android_vpn_visible=unknown"))
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
