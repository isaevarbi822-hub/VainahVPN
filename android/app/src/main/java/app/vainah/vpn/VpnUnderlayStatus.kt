package app.vainah.vpn

import android.content.Context

/**
 * Private, bounded network-handoff facts only: no network names, IPs,
 * SSIDs, hostnames, VLESS URLs, subscriber IDs or bearer credentials.
 *
 * An Android VALIDATED underlay is NOT proof the VPN tunnel works.
 */
object VpnUnderlayStatus {
    private const val PREF = "vainah_underlay_status_v1"
    private val allowed = setOf("wifi", "cellular", "ethernet", "other", "none")

    data class Snapshot(
        val transport: String,
        val validated: Boolean,
        val transitions: Int,
        val event: String,
    )

    fun record(context: Context, transport: String, validated: Boolean) {
        val safe = transport.takeIf { it in allowed } ?: "other"
        val prefs = context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
        val old = prefs.getString("transport", "none") ?: "none"
        val oldValidated = prefs.getBoolean("validated", false)
        if (old == safe && oldValidated == validated) return
        val event = when {
            old == "none" && safe != "none" -> "underlay_available"
            old != "none" && safe == "none" -> "underlay_lost"
            old != safe -> "underlay_changed"
            else -> "underlay_validation_changed"
        }
        val transitions = (prefs.getInt("transitions", 0) + if (old != safe && old != "none") 1 else 0)
            .coerceIn(0, 9999)
        prefs.edit()
            .putString("transport", safe)
            .putBoolean("validated", validated)
            .putString("event", event)
            .putInt("transitions", transitions)
            .commit()
    }

    fun read(context: Context): Snapshot {
        val prefs = context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
        val value = prefs.getString("transport", "none") ?: "none"
        val event = prefs.getString("event", "not_checked") ?: "not_checked"
        return Snapshot(
            value.takeIf { it in allowed } ?: "none",
            prefs.getBoolean("validated", false),
            prefs.getInt("transitions", 0).coerceIn(0, 9999),
            event.takeIf { it in setOf(
                "not_checked", "underlay_available", "underlay_lost",
                "underlay_changed", "underlay_validation_changed"
            ) } ?: "not_checked"
        )
    }

    fun reset(context: Context) {
        context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
            .edit().clear().commit()
    }
}
