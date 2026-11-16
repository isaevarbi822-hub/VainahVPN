package app.vainah.vpn

/** Sizes the neon connect dial without clipping on narrow Android screens. */
internal object PremiumHomeLayout {
    const val MAX_DIAL_DP = 242
    const val MIN_DIAL_DP = 96
    const val SIDE_SPACE_DP = 45

    fun dialSizeDp(screenWidthDp: Int): Int =
        (screenWidthDp - SIDE_SPACE_DP).coerceIn(MIN_DIAL_DP, MAX_DIAL_DP)
}
