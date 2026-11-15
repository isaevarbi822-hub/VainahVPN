package app.vainah.vpn

import java.net.URI
import java.net.URLDecoder
import java.util.Locale
import java.util.UUID

/**
 * Parse supported and display-only VLESS subscription entries without exposing
 * their credentials in UI. Only the previously validated TCP/REALITY profile
 * may be passed to the current libbox engine.
 */
object SubscriptionNodeSupport {
    data class Details(
        val transport: String,
        val security: String,
        val connectable: Boolean,
    ) {
        val subtitle: String
            get() = "VLESS / ${transport.uppercase(Locale.ROOT)} / " +
                security.uppercase(Locale.ROOT)
    }

    fun inspect(raw: String): Details? = runCatching {
        if (raw.length !in 1..8192) return null
        val uri = URI(raw)
        if (uri.scheme != "vless" || uri.host.isNullOrBlank() ||
            uri.host!!.length > 253 || uri.port !in 1..65535) return null
        val id = uri.rawUserInfo ?: return null
        if (!id.matches(Regex("[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")))
            return null
        UUID.fromString(id)
        val params = uri.rawQuery.orEmpty().split('&').mapNotNull { part ->
            val p = part.indexOf('=')
            if (p <= 0) null
            else URLDecoder.decode(part.substring(0, p), "UTF-8").lowercase(Locale.ROOT) to
                URLDecoder.decode(part.substring(p + 1), "UTF-8")
        }.toMap()
        val security = params["security"]?.lowercase(Locale.ROOT) ?: "none"
        if (security !in setOf("tls", "reality")) return null
        if (security == "reality" &&
            (params["pbk"].isNullOrBlank() || params["sni"].isNullOrBlank())) return null
        val network = (params["type"] ?: "tcp").lowercase(Locale.ROOT)
        if (network !in setOf("tcp", "raw", "grpc", "xhttp", "splithttp")) return null
        val normalized = when(network) {
            "raw" -> "tcp"
            "splithttp" -> "xhttp"
            else -> network
        }
        Details(normalized, security,
            runCatching { VlessRealityConfig.outbound(raw) }.isSuccess)
    }.getOrNull()

    fun canConnect(raw: String): Boolean = inspect(raw)?.connectable == true
}
