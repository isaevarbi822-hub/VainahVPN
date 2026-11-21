package app.vainah.vpn

import java.net.URI

/**
 * A subscription URL is a bearer credential. No network request, no logging.
 * We deliberately accept HTTPS subscriptions, NOT raw vless:// links.
 */
object SubscriptionLink {
    fun validate(raw: String): String? {
        val value = raw.trim()
        if (value.length !in 12..2048 || value.any { it.isWhitespace() || it.isISOControl() }) return null
        return try {
            val u = URI(value)
            if (u.scheme != "https" || u.host.isNullOrBlank() || u.rawUserInfo != null ||
                u.rawFragment != null || u.port !in -1..65535 ||
                (u.port != -1 && u.port < 1) ||
                u.host!!.length > 253 ||
                u.host!!.contains("..") || u.host!!.contains("\\")
            ) null else value
        } catch (_: Exception) { null }
    }
}
