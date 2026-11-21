package app.vainah.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SplitTunnelPolicyTest {
    private val ownPackage = "app.vainah.vpn.next"

    @Test fun defaultsCaptureAllApplications() {
        assertTrue(SplitTunnelPolicy.normalize(emptyList(), ownPackage).isEmpty())
        assertTrue(SplitTunnelPolicy.effectiveExclusions(
            emptyList(), ownPackage, lockdownEnabled = false
        ).isEmpty())
    }

    @Test fun selectedPackagesBypassOnlyWhenLockdownIsOff() {
        val selected = listOf("com.example.mail", "org.example.chat")
        assertEquals(selected.toSet(), SplitTunnelPolicy.effectiveExclusions(
            selected, ownPackage, lockdownEnabled = false
        ))
        assertTrue(SplitTunnelPolicy.effectiveExclusions(
            selected, ownPackage, lockdownEnabled = true
        ).isEmpty())
    }

    @Test fun protectsTheVpnAppItself() {
        assertTrue(SplitTunnelPolicy.normalize(
            listOf(ownPackage), ownPackage
        ).isEmpty())
    }

    @Test fun rejectsMalformedOrOverlongPackageNames() {
        for (bad in listOf(
            "", "com", "com..example", "../com.example", "com.example;exit",
            "com.example\nnext", "1org.example", "org.example" + "x".repeat(181)
        )) {
            assertTrue(SplitTunnelPolicy.normalize(listOf(bad), ownPackage).isEmpty())
        }
    }

    @Test fun rejectsTooManyAppsInsteadOfSilentPartialBypass() {
        val names = (1..13).map { "com.example.package$it" }
        assertTrue(SplitTunnelPolicy.normalize(names, ownPackage).isEmpty())
        assertEquals(12, SplitTunnelPolicy.normalize(
            names.take(12), ownPackage
        ).size)
    }

    @Test fun sortsAndDeduplicatesSelections() {
        assertEquals(
            setOf("com.example.alpha", "org.example.beta"),
            SplitTunnelPolicy.normalize(
                listOf("org.example.beta", "com.example.alpha", "org.example.beta"),
                ownPackage
            )
        )
    }
}
