package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class VainahThemeTest {
    @Test fun premiumDarkThemeIsDefault() {
        assertEquals(VainahTheme.Mode.DARK, VainahTheme.parse(null))
        assertEquals(VainahTheme.Mode.DARK, VainahTheme.parse("UNKNOWN"))
        assertEquals(VainahTheme.Mode.LIGHT, VainahTheme.parse("LIGHT"))
    }

    @Test fun allRealAppearanceOptionsRoundTrip() {
        for (mode in VainahTheme.Mode.values()) {
            assertEquals(mode, VainahTheme.parse(mode.name))
            assertTrue(VainahTheme.label(mode).isNotBlank())
        }
    }

    @Test fun customThemeDoesNotExposeVpnOrAccountSecrets() {
        val labels = VainahTheme.Mode.values().map(VainahTheme::label)
        assertEquals(3, labels.distinct().size)
        assertTrue(labels.none { it.contains("token", true) })
    }
}
