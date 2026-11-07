package app.vainah.vpn

import android.content.Context
import android.os.SystemClock

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
        if (old == safe && oldValidated == validated && prefs.contains("transport")) return
        val event = when {
            old == "none" && safe == "none" -> "underlay_lost"
            old == "none" && safe != "none" -> "underlay_available"
            old != "none" && safe == "none" -> "underlay_lost"
            old != safe -> "underlay_changed"
            else -> "underlay_validation_changed"
        }
        val transitions = (prefs.getInt("transitions", 0) + if (old != safe && old != "none") 1 else 0)
            .coerceIn(0, 9999)
        val journal = VpnHandoffJournal.append(
            prefs.getString("recent_events", null),
            VpnHandoffEvent(old, safe, event, validated),
        )
        val now = SystemClock.elapsedRealtime()
        val previousOfflineAt = prefs.getLong("offline_since_elapsed", -1L)
        val outageMs = if (old == "none" && safe != "none") {
            VpnRecoveryAdvisor.ageSince(now, previousOfflineAt)
        } else null
        val edit = prefs.edit()
            .putString("transport", safe)
            .putBoolean("validated", validated)
            .putString("event", event)
            .putInt("transitions", transitions)
            .putString("recent_events", journal)
        if (safe == "none") {
            if (previousOfflineAt <= 0L ||
                VpnRecoveryAdvisor.ageSince(now, previousOfflineAt) == null
            ) edit.putLong("offline_since_elapsed", now)
        } else {
            edit.remove("offline_since_elapsed")
            if (old == "none") edit.putLong("last_outage_ms", outageMs ?: -1L)
        }
        edit.commit()
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

    fun recovery(context: Context, vpnActive: Boolean): VpnRecoveryAdvice {
        val prefs = context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
        val snapshot = read(context)
        val now = SystemClock.elapsedRealtime()
        val offline = if (snapshot.transport == "none")
            VpnRecoveryAdvisor.ageSince(
                now, prefs.getLong("offline_since_elapsed", -1L)
            )
        else null
        val lastDuration = prefs.getLong("last_outage_ms", -1L).takeIf {
            it in 0..VpnRecoveryAdvisor.MAX_TRACKED_MS
        }
        return VpnRecoveryAdvisor.advice(VpnRecoveryState(
            vpnActive, snapshot.transport, snapshot.validated, offline, lastDuration
        ))
    }

    fun history(context: Context): List<VpnHandoffEvent> =
        VpnHandoffJournal.parse(
            context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
                .getString("recent_events", null)
        )

    fun reportHistory(context: Context): String =
        VpnHandoffJournal.sanitizedReport(
            context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
                .getString("recent_events", null)
        )

    fun reset(context: Context) {
        context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
            .edit().clear().commit()
    }
}
