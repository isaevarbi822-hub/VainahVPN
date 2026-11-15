package app.vainah.vpn

import android.graphics.Color

/** Android-only light design tokens. Website and iOS themes are unchanged. */
object VainahDesign {
    // Original light UI inspired by the supplied layout reference.
    // One palette is shared across ALL Android screens.
    val background: Int = Color.rgb(249, 247, 254) // #F6F7FA
    val surface: Int = Color.rgb(255, 255, 255)     // #FFFFFF
    val surface2: Int = Color.rgb(253, 250, 255)    // #FCFCFF
    val border: Int = Color.rgb(230, 221, 244)      // #E3E6EF
    val muted: Int = Color.rgb(117, 115, 137)       // #848A9B
    val ink: Int = Color.rgb(49, 34, 70)           // #25283D
    val purple: Int = Color.rgb(111, 60, 181)     // #6F6FB1
    val sky: Int = Color.rgb(83, 115, 162)         // #427F9E
    val green: Int = Color.rgb(21, 126, 78)       // #198B6B
    val softPurple: Int = Color.rgb(222, 208, 245) // #D6D6EE
    val accentDark: Int = Color.rgb(84, 36, 145)   // #555490
    val previewTop: Int = Color.rgb(252, 249, 255)
    val previewBottom: Int = Color.rgb(243, 238, 254)
    val inactive: Int = Color.rgb(241, 232, 251)
    val error: Int = Color.rgb(184, 63, 75)        // readable on white
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
