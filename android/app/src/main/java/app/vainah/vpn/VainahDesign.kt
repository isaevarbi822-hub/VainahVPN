package app.vainah.vpn

import android.graphics.Color

/** Android-only light design tokens. Website and iOS themes are unchanged. */
object VainahDesign {
    // Original light UI inspired by the supplied layout reference.
    // One palette is shared across ALL Android screens.
    val background: Int = Color.rgb(246, 247, 250) // #F6F7FA
    val surface: Int = Color.rgb(255, 255, 255)     // #FFFFFF
    val surface2: Int = Color.rgb(252, 252, 255)    // #FCFCFF
    val border: Int = Color.rgb(227, 230, 239)      // #E3E6EF
    val muted: Int = Color.rgb(132, 138, 155)       // #848A9B
    val ink: Int = Color.rgb(37, 40, 61)           // #25283D
    val purple: Int = Color.rgb(111, 111, 177)     // #6F6FB1
    val sky: Int = Color.rgb(66, 127, 158)         // #427F9E
    val green: Int = Color.rgb(25, 139, 107)       // #198B6B
    val softPurple: Int = Color.rgb(214, 214, 238) // #D6D6EE
    val accentDark: Int = Color.rgb(85, 84, 144)   // #555490
    val previewTop: Int = Color.rgb(254, 254, 255)
    val previewBottom: Int = Color.rgb(241, 242, 249)
    val inactive: Int = Color.rgb(238, 239, 247)
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
