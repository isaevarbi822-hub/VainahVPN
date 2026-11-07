package app.vainah.vpn

import android.content.Context

/**
 * User-selected application bypass for Android VpnService.Builder.
 *
 * This is NOT a kill switch. Excluded apps can use the underlying network
 * without the VPN. Android lockdown ("Block connections without VPN") takes
 * precedence and forbids this bypass.
 */
object SplitTunnelPolicy {
    const val MAX_EXCLUDED_APPS = 12
    private val packagePattern = Regex("[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)+")

    fun normalize(values: Collection<String>, ownPackage: String): Set<String> {
        if (values.size > MAX_EXCLUDED_APPS) return emptySet()
        if (values.any { it.length > 180 || !packagePattern.matches(it) || it == ownPackage }) {
            return emptySet()
        }
        return values.toSortedSet()
    }

    fun effectiveExclusions(
        configured: Collection<String>,
        ownPackage: String,
        lockdownEnabled: Boolean,
    ): Set<String> {
        if (lockdownEnabled) return emptySet()
        return normalize(configured, ownPackage)
    }
}

object SplitTunnelPreferences {
    private const val NAME = "vainah_split_tunnel_v1"
    private const val KEY = "excluded_apps"
    fun read(context: Context): Set<String> =
        SplitTunnelPolicy.normalize(
            context.getSharedPreferences(NAME, Context.MODE_PRIVATE)
                .getStringSet(KEY, emptySet()) ?: emptySet(),
            context.packageName,
        )

    fun save(context: Context, selected: Collection<String>): Boolean {
        val result = SplitTunnelPolicy.normalize(selected, context.packageName)
        if (result.size != selected.toSet().size) return false
        // commit avoids a connection racing with an in-flight asynchronous apply.
        return context.getSharedPreferences(NAME, Context.MODE_PRIVATE)
            .edit().putStringSet(KEY, result.toSet()).commit()
    }
}
