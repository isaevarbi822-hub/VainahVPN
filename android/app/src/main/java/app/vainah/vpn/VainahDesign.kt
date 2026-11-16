package app.vainah.vpn

import android.graphics.Color

/** Accessible, unified light/dark lavender palette for all VainahVPN screens. */
object VainahDesign {
    val background: Int get() = if (VainahTheme.isDark)
        Color.rgb(12, 10, 23) else Color.rgb(249, 247, 254)
    val surface: Int get() = if (VainahTheme.isDark)
        Color.rgb(27, 23, 43) else Color.WHITE
    val surface2: Int get() = if (VainahTheme.isDark)
        Color.rgb(36, 29, 55) else Color.rgb(253, 250, 255)
    val border: Int get() = if (VainahTheme.isDark)
        Color.rgb(80, 64, 113) else Color.rgb(230, 221, 244)
    val muted: Int get() = if (VainahTheme.isDark)
        Color.rgb(195, 184, 209) else Color.rgb(117, 115, 137)
    val ink: Int get() = if (VainahTheme.isDark)
        Color.rgb(250, 246, 255) else Color.rgb(49, 34, 70)
    val purple: Int get() = if (VainahTheme.isDark)
        Color.rgb(166, 85, 255) else Color.rgb(111, 60, 181)
    val sky: Int get() = if (VainahTheme.isDark)
        Color.rgb(142, 184, 238) else Color.rgb(83, 115, 162)
    val green: Int get() = if (VainahTheme.isDark)
        Color.rgb(119, 222, 164) else Color.rgb(21, 126, 78)
    val softPurple: Int get() = if (VainahTheme.isDark)
        Color.rgb(94, 71, 118) else Color.rgb(222, 208, 245)
    val accentDark: Int get() = if (VainahTheme.isDark)
        Color.rgb(104, 36, 207) else Color.rgb(84, 36, 145)
    val previewTop: Int get() = if (VainahTheme.isDark)
        Color.rgb(13, 10, 25) else Color.rgb(252, 249, 255)
    val previewBottom: Int get() = if (VainahTheme.isDark)
        Color.rgb(25, 19, 43) else Color.rgb(243, 238, 254)
    val inactive: Int get() = if (VainahTheme.isDark)
        Color.rgb(64, 44, 83) else Color.rgb(241, 232, 251)
    val error: Int get() = if (VainahTheme.isDark)
        Color.rgb(255, 143, 158) else Color.rgb(184, 63, 75)
}

/**
 * Never ship fixed tariff amounts in a mobile APK.
 *
 * Purchases and current terms are served by the authenticated Python website;
 * older APK prototypes used an obsolete six-item hardcoded price list.
 */
data class VainahPlan(
    val id: String, val days: Int, val title: String,
    val priceRub: Int, val deviceLimit: Int, val badge: String,
)

@Deprecated("Read current plans from the server-side website, not the APK.")
object VainahPlans {
    val all: List<VainahPlan> = emptyList()
}
