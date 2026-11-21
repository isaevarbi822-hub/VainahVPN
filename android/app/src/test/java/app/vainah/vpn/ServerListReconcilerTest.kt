package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class ServerListReconcilerTest {
    private fun node(label: String, id: Int) = VainahNode(label, "vless://test${id}@example.invalid:443")

    @Test fun newLocationsAreIncludedWithoutReinstall() {
        val original = listOf(node("🇩🇪 Германия", 1))
        val next = ServerListReconciler.unique(original + node("🇳🇴 Норвегия", 2))
        assertEquals(2, next.size)
        assertEquals("🇳🇴 Норвегия", next.last().label)
    }

    @Test fun duplicateSubscriptionsDoNotShowDuplicateServers() {
        val a = node("Germany", 1)
        val b = node("Norway", 2)
        assertEquals(listOf(a,b), ServerListReconciler.unique(listOf(a,a,b,b)))
    }

    @Test fun selectedServerSurvivesReorderingAndRename() {
        val previous = node("Germany", 1)
        val renamed = previous.copy(label = "🇩🇪 Германия · Premium")
        val available = listOf(node("Spain", 3), renamed)
        assertEquals(renamed, ServerListReconciler.preserve(previous, available))
    }

    @Test fun removedServerIsNotSilentlyReplaced() {
        assertNull(ServerListReconciler.preserve(node("Germany", 1),
            listOf(node("Germany", 99), node("Norway", 2))))
    }

    @Test fun rotatedCredentialsRequireExplicitReselection() {
        val previous = node("Norway", 1)
        assertNull(ServerListReconciler.preserve(previous,
            listOf(node("Norway", 2))))
    }

    @Test fun emptyOrUnselectedListsRemainUnselected() {
        assertNull(ServerListReconciler.preserve(null, listOf(node("Norway", 2))))
        assertNull(ServerListReconciler.preserve(node("Germany", 1), emptyList()))
    }
}
