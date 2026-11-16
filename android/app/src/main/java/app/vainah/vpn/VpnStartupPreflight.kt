package app.vainah.vpn

/**
 * Distinguishes local subscription storage from profile compatibility.
 * No VLESS URL, key, host, or native exception text is persisted or exposed.
 */
internal object VpnStartupPreflight {
    fun failureStage(
        engineReady: Boolean,
        subscriptionPresent: Boolean,
        profileValid: Boolean
    ): String? = when {
        !engineReady -> "engine_unavailable"
        !subscriptionPresent -> "subscription_storage_unavailable"
        !profileValid -> "validating_selected_profile"
        else -> null
    }
}
