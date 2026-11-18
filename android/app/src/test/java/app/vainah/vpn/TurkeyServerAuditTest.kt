package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

/** Fully synthetic VLESS nodes; these tests never contact Turkey or H1Cloud. */
class TurkeyServerAuditTest {
    private val fakeUuid = "00000000-0000-4000-8000-000000000001"
    private val tcp = "vless://$fakeUuid@example.org:443" +
        "?security=reality&type=tcp&sni=example.org" +
        "&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    private fun node(name: String, profile: String = tcp) = VainahNode(name, profile)

    @Test fun twoRequestedServersAreFoundWithHumanReadableSpaceLabels() {
        val checks = TurkeyServerAudit.inspect(listOf(
            node("Турция 1"), node("Турция IP"), node("Турция 10")
        ))
        assertEquals(2, checks.size)
        assertEquals(TurkeyLteGroups.Slot.ONE, checks[0].slot)
        assertEquals(TurkeyLteGroups.Slot.IP, checks[1].slot)
        for (check in checks) {
            assertEquals(TurkeyServerAudit.Status.READY, check.status)
            assertEquals(1, check.importedCount)
            assertTrue(check.headline.contains("VPN не проверен"))
            assertEquals("locally_parseable_not_connected", check.safeDiagnostic)
            assertFalse(check.explanation.contains("example.org"))
            assertFalse(check.explanation.contains(fakeUuid))
        }
    }

    @Test fun noImportedNodesMeansSubscriptionNotLoadedNotDeletedTurkeyServer() {
        val checks = TurkeyServerAudit.inspect(emptyList())
        assertEquals(2, checks.size)
        assertTrue(checks.all { it.status == TurkeyServerAudit.Status.NOT_LOADED })
        assertTrue(checks.all { it.safeDiagnostic == "subscription_not_loaded" })
        assertTrue(checks.all { it.importedCount == 0 })
        assertTrue(checks.all { it.explanation.contains("не получило список") })
    }

    @Test fun missingServerNeverGetsInventedAndIsNotReportedOnline() {
        val checks = TurkeyServerAudit.inspect(listOf(
            node("Албания 1"), node("Турция IP")
        ))
        assertEquals(TurkeyServerAudit.Status.MISSING, checks[0].status)
        assertEquals("not_found_by_label", checks[0].safeDiagnostic)
        assertEquals(0, checks[0].importedCount)
        assertTrue(checks[0].headline.contains("названием"))
        assertEquals(TurkeyServerAudit.Status.READY, checks[1].status)
    }

    @Test fun badXhttpExtrasGiveSafeLocalRejectionNotSubscriptionExpiry() {
        val bad = tcp.replace("type=tcp", "type=xhttp") +
            "&extra=%7B%22downloadSettings%22%3A%7B%22address%22%3A%22private.example%22%7D%7D"
        val checks = TurkeyServerAudit.inspect(listOf(node("Турция IP", bad)))
        assertEquals(TurkeyServerAudit.Status.UNSUPPORTED, checks[1].status)
        assertTrue(checks[1].safeDiagnostic.startsWith("local_profile_rejected_"))
        assertFalse(checks[1].safeDiagnostic.contains("private.example"))
        assertFalse(checks[1].explanation.contains("private.example"))
        assertFalse(checks[1].explanation.contains("vless://"))
        assertFalse(checks[1].explanation.contains(fakeUuid))
    }

    @Test fun oneCompatibleDuplicateIsEnoughToOfferAttemptWithoutClaimingSuccess() {
        val invalid = "vless://not-a-uuid@private.example:443"
        val checks = TurkeyServerAudit.inspect(listOf(
            node("Турция 1", invalid), node("Turkey 1", tcp)
        ))
        assertEquals(TurkeyServerAudit.Status.READY, checks[0].status)
        assertEquals(2, checks[0].importedCount)
        assertTrue(checks[0].explanation.contains("не проверка"))
    }

    @Test fun exportedDiagnosticsOnlyUseFixedCodesAndNeverUris() {
        val entries = TurkeyServerAudit.inspect(listOf(node("Турция IP", tcp)))
        val report = VpnDiagnosticReport.create(
            phase = "off", lastStage = null, probeReason = null,
            androidApiLevel = 37, serviceRunning = false, turkeyAudit = entries
        )
        assertTrue(report.contains("turkey_1_local_profile=not_found_by_label"))
        assertTrue(report.contains("turkey_ip_local_profile=locally_parseable_not_connected"))
        assertFalse(report.contains("example.org"))
        assertFalse(report.contains(fakeUuid))
        assertFalse(report.contains("vless://"))
    }

    @Test fun maliciousRejectionStringCannotReachSupportReport() {
        val fake = TurkeyServerAudit.Entry(TurkeyLteGroups.Slot.IP,
            TurkeyServerAudit.Status.UNSUPPORTED, 1,
            "vless://private.example/\npassword=secret"
        )
        val report = VpnDiagnosticReport.create(
            phase = "off", lastStage = null, probeReason = null,
            androidApiLevel = 37, serviceRunning = false,
            turkeyAudit = listOf(fake)
        )
        assertTrue(report.contains("turkey_ip_local_profile=local_profile_rejected_unknown"))
        assertFalse(report.contains("private.example"))
        assertFalse(report.contains("password=secret"))
    }
}
