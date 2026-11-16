package app.vainah.vpn

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Credential-free local history of state changes only. No server address,
 * user ID, VPN key, browser URL, website activity or traffic contents.
 * Bounded to 20 events, stored only on device, user can erase any time.
 */
object VpnSessionJournal {
    private const val PREF = "vainah_vpn_history_v3"
    private const val LIMIT = 20
    private val allowed = setOf(
        VpnConnectionState.STARTING,
        VpnConnectionState.TUN_READY,
        VpnConnectionState.FAILED,
        VpnConnectionState.OFF
    )

    data class Event(val timestamp: Long, val phase: String)

    fun shouldRecord(previous: String, next: String): Boolean =
        next in allowed && previous != next

    fun record(context: Context, previous: String, next: String) {
        if (!shouldRecord(previous, next)) return
        runCatching {
            val prefs = context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
            val current = JSONArray(prefs.getString("entries", "[]"))
            val ordered = (0 until current.length()).mapNotNull { i ->
                val item = current.optJSONObject(i)
                val phase = item?.optString("phase").orEmpty()
                val timestamp = item?.optLong("time", -1) ?: -1L
                if (phase in allowed && timestamp > 0)
                    Event(timestamp, phase) else null
            }.takeLast(LIMIT - 1)
            val updated = JSONArray()
            for (event in ordered) {
                updated.put(JSONObject()
                    .put("time", event.timestamp)
                    .put("phase", event.phase))
            }
            updated.put(JSONObject().put("time", System.currentTimeMillis())
                .put("phase", next))
            prefs.edit().putString("entries", updated.toString()).apply()
        }
    }

    fun read(context: Context): List<Event> = runCatching {
        val prefs = context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
        val array = JSONArray(prefs.getString("entries", "[]"))
        (0 until array.length()).mapNotNull { i ->
            val obj = array.optJSONObject(i)
            val phase = obj?.optString("phase").orEmpty()
            val timestamp = obj?.optLong("time", -1) ?: -1L
            if (phase in allowed && timestamp > 0)
                Event(timestamp, phase) else null
        }.takeLast(LIMIT).asReversed()
    }.getOrDefault(emptyList())

    fun clear(context: Context) {
        context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
            .edit().clear().apply()
    }

    fun title(phase: String): String = when(phase) {
        VpnConnectionState.STARTING -> "Попытка подключения"
        VpnConnectionState.TUN_READY -> "Туннель создан"
        VpnConnectionState.FAILED -> "Ошибка VPN"
        VpnConnectionState.OFF -> "VPN отключён"
        else -> "Неизвестное событие"
    }

    fun localTime(timestamp: Long): String =
        SimpleDateFormat("dd.MM HH:mm", Locale.getDefault())
            .format(Date(timestamp))
}
