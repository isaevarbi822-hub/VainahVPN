package app.vainah.vpn

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Read-only native billing capability check. RollyPay invoices, auth cookies,
 * webhook verification, order status and VPN delivery stay SERVER-SIDE.
 *
 * No merchant credentials or subscription URLs ever enter this class.
 * If the server is unavailable or returns invalid data, billing fails closed.
 */
object NativeCheckout {
    const val SITE = "https://vainahvpnbot0.netlify.app"
    private const val STATUS_URL = "$SITE/.netlify/functions/subscription-plans"

    data class Availability(
        val serverReady: Boolean,
        val pricesMatch: Boolean
    ) {
        val permitted: Boolean get() = serverReady && pricesMatch
    }

    fun parseAvailability(json: String): Availability {
        return try {
            val payload = JSONObject(json)
            val entries = payload.getJSONArray("plans")
            val expected = VainahPlans.all
            if (entries.length() != expected.size) return Availability(false, false)
            val seen = HashSet<String>()
            for (i in 0 until entries.length()) {
                val item = entries.getJSONObject(i)
                val plan = expected.firstOrNull { it.id == item.optString("id") }
                    ?: return Availability(false, false)
                if (!seen.add(plan.id) ||
                    item.optInt("days", -1) != plan.days ||
                    item.optInt("deviceLimit", -1) != plan.deviceLimit ||
                    item.optString("priceRub") != "%.2f".format(java.util.Locale.ROOT, plan.priceRub.toDouble())
                ) return Availability(false, false)
            }
            Availability(payload.optBoolean("nativeCheckoutReady", false), true)
        } catch (_: Exception) {
            Availability(false, false)
        }
    }

    fun fetchAvailability(): Availability {
        val conn = (URL(STATUS_URL).openConnection() as HttpURLConnection)
        try {
            conn.connectTimeout = 4500
            conn.readTimeout = 4500
            conn.instanceFollowRedirects = false
            conn.setRequestProperty("Accept", "application/json")
            conn.useCaches = false
            if (conn.responseCode != 200) return Availability(false, false)
            if (conn.contentLengthLong > 20_000) return Availability(false, false)
            val bytes = conn.inputStream.use { input ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(4096)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    if (output.size() + read > 20_000) return Availability(false, false)
                    output.write(buffer, 0, read)
                }
                output.toByteArray()
            }
            return parseAvailability(String(bytes, Charsets.UTF_8))
        } catch (_: Exception) {
            return Availability(false, false)
        } finally {
            conn.disconnect()
        }
    }

    /** Only a built-in canonical plan ID can become a checkout query value. */
    fun checkoutUrl(planId: String): String? {
        if (VainahPlans.all.none { it.id == planId }) return null
        return "$SITE/checkout.html?plan=$planId"
    }
}
