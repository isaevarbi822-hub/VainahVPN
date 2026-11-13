package app.vainah.vpn

import android.content.Context
import android.os.Build
import java.util.UUID

/**
 * Some subscription panels require X-HWID for device accounting.
 * Never reuse or impersonate another VPN client's identifier.
 *
 * OFF by default: no device identifier, Android version, or model is sent
 * unless the user opts in. The ID is a randomly generated, app-specific
 * UUID saved in this app's private storage for stability across updates.
 */
class SubscriptionHwid(context: Context) {
    private val prefs = context.getSharedPreferences(
        "vainah_subscription_device", Context.MODE_PRIVATE
    )

    fun isEnabled(): Boolean = prefs.getBoolean("hwid_enabled", false)

    fun setEnabled(enabled: Boolean): Boolean =
        prefs.edit().putBoolean("hwid_enabled", enabled).commit()

    fun requestHeaders(): Map<String, String> {
        if (!isEnabled()) return emptyMap()
        val id = synchronized(this) {
            var existing = prefs.getString("hwid_v1", null)
            if (!SubscriptionHwidHeaders.validId(existing)) {
                existing = UUID.randomUUID().toString()
                // Do not send a changing identifier if private storage failed.
                if (!prefs.edit().putString("hwid_v1", existing).commit())
                    return emptyMap()
            }
            existing
        }
        return SubscriptionHwidHeaders.build(
            id, Build.VERSION.RELEASE ?: "", Build.MODEL ?: ""
        )
    }
}

object SubscriptionHwidHeaders {
    private val allowedId = Regex("^[A-Za-z0-9=-]{10,64}$")
    fun validId(value: String?): Boolean = value != null &&
        allowedId.matches(value)

    // Never send unbounded or non-printable values in HTTP request headers.
    private fun clean(value: String): String =
        value.filter { it.code in 32..126 }.take(64)

    fun build(id: String?, osVersion: String, model: String): Map<String, String> {
        if (!validId(id)) return emptyMap()
        return buildMap {
            put("X-HWID", id!!)
            put("X-Device-Os", "Android")
            clean(osVersion).takeIf { it.isNotBlank() }?.let { put("X-Ver-Os", it) }
            clean(model).takeIf { it.isNotBlank() }?.let { put("X-Device-Model", it) }
        }
    }
}
