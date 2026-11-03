package app.vainah.vpn

import android.graphics.Color

/**
 * Brand tokens mirror the CSS variables on site/index.html.
 * Keep in sync with native/ios/Sources/App/VainahDesign.swift.
 */
object VainahDesign {
    val background: Int = Color.rgb(8, 11, 21)  // #080b15
    val surface: Int = Color.rgb(18, 22, 38)     // #121626
    val surface2: Int = Color.rgb(24, 27, 47)    // #181b2f
    val border: Int = Color.rgb(41, 45, 67)      // #292d43
    val muted: Int = Color.rgb(160, 166, 189)    // #a0a6bd
    val ink: Int = Color.rgb(245, 246, 255)      // #f5f6ff
    val purple: Int = Color.rgb(169, 139, 255)   // #a98bff
    val sky: Int = Color.rgb(121, 205, 233)      // #79cde9
    val green: Int = Color.rgb(112, 229, 177)    // #70e5b1
    val softPurple: Int = Color.rgb(205, 185, 255)
    val accentDark: Int = Color.rgb(101, 60, 224)
    val previewTop: Int = Color.rgb(37, 34, 71) // #252247
    val previewBottom: Int = Color.rgb(19, 27, 52) // #131b34
    val inactive: Int = Color.rgb(15, 21, 39)
}

/** The SAME 6 canonical plans as netlify/functions/lib/plan-catalog.mjs. */
data class VainahPlan(
    val id: String, val days: Int, val title: String,
    val priceRub: Int, val deviceLimit: Int, val badge: String
)
object VainahPlans {
    val all: List<VainahPlan> = listOf(
        VainahPlan("30", 30, "1 месяц", 99, 3, "НАЧАТЬ С МАЛОГО"),
        VainahPlan("60", 60, "2 месяца", 160, 3, "60 ДНЕЙ"),
        VainahPlan("90", 90, "3 месяца", 219, 3, "90 ДНЕЙ"),
        VainahPlan("180", 180, "6 месяцев", 339, 3, "180 ДНЕЙ"),
        VainahPlan("365", 365, "1 год", 700, 3, "365 ДНЕЙ"),
        VainahPlan("365-family", 365, "1 год · семейный", 1000, 6, "СЕМЕЙНЫЙ")
    )
}
