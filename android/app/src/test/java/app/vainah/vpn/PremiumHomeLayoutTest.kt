package app.vainah.vpn

import org.junit.Assert.assertEquals
import org.junit.Test

class PremiumHomeLayoutTest {
    @Test fun powerDialFitsNarrowAndRegularAndroidLayouts() {
        assertEquals(242, PremiumHomeLayout.dialSizeDp(420))
        assertEquals(242, PremiumHomeLayout.dialSizeDp(360))
        assertEquals(195, PremiumHomeLayout.dialSizeDp(240))
        assertEquals(131, PremiumHomeLayout.dialSizeDp(176))
        assertEquals(96, PremiumHomeLayout.dialSizeDp(120))
    }
}
