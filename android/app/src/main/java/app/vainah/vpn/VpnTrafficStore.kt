package app.vainah.vpn

import android.content.Context
import android.os.SystemClock
import java.util.Locale

/**
 * Shares only libbox's native traffic counters between the foreground
 * service and the UI. No packet contents, URLs, IPs, or server secrets.
 *
 * A status without trafficAvailable is NOT silently displayed as 0 B/s.
 * Data older than 5 seconds is unavailable rather than deceptively live.
 */
object VpnTrafficStore {
    data class Sample(
        val uplink: Long,
        val downlink: Long,
        val uplinkTotal: Long,
        val downlinkTotal: Long
    )

    private const val PREF = "vainah_vpn_traffic"
    private const val MAX_AGE_MS = 5_000L

    fun clear(context: Context) {
        context.getSharedPreferences(PREF, Context.MODE_PRIVATE).edit()
            .clear().commit()
    }

    fun publish(context: Context, sample: Sample, available: Boolean) {
        if (!available || listOf(sample.uplink, sample.downlink,
                sample.uplinkTotal, sample.downlinkTotal).any { it < 0 }) {
            clear(context)
            return
        }
        context.getSharedPreferences(PREF, Context.MODE_PRIVATE).edit()
            .putLong("last_elapsed", SystemClock.elapsedRealtime())
            .putLong("up", sample.uplink)
            .putLong("down", sample.downlink)
            .putLong("up_total", sample.uplinkTotal)
            .putLong("down_total", sample.downlinkTotal)
            .apply()
    }

    fun read(context: Context): Sample? {
        val prefs = context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
        if (!prefs.contains("last_elapsed")) return null
        val age = SystemClock.elapsedRealtime() - prefs.getLong("last_elapsed", 0L)
        if (age < 0 || age > MAX_AGE_MS) return null
        return Sample(
            uplink = prefs.getLong("up", -1),
            downlink = prefs.getLong("down", -1),
            uplinkTotal = prefs.getLong("up_total", -1),
            downlinkTotal = prefs.getLong("down_total", -1)
        ).takeIf { listOf(it.uplink, it.downlink,
            it.uplinkTotal, it.downlinkTotal).all { number -> number >= 0 } }
    }

    fun format(bytes: Long): String {
        if (bytes < 0) return "—"
        if (bytes < 1024) return "$bytes Б"
        val units = arrayOf("КиБ", "МиБ", "ГиБ", "ТиБ")
        var value = bytes.toDouble()
        var index = -1
        while (value >= 1024 && index < units.lastIndex) {
            value /= 1024
            index++
        }
        return String.format(Locale.ROOT, "%.1f %s", value, units[index])
    }
}
