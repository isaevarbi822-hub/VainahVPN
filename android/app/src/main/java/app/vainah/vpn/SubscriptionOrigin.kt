package app.vainah.vpn

import java.net.URI
import java.util.Locale

/**
 * Describe only the type of endpoint. The real URL may contain a bearer token;
 * never show its domain, path, query, credentials or fragment in UI/logs.
 */
object SubscriptionOrigin {
    enum class Kind { NONE, H1CLOUD, PYTHON_RENDER, LEGACY_NETLIFY, OTHER_HTTPS, DIRECT_KEY }

    fun fromLink(raw: String?): Kind {
        if (raw == null) return Kind.NONE
        if (SubscriptionInput.isDirectKey(raw)) return Kind.DIRECT_KEY
        val valid = SubscriptionLink.validate(raw) ?: return Kind.NONE
        val host = try { URI(valid).host?.lowercase(Locale.ROOT) ?: return Kind.NONE }
                   catch (_: Exception) { return Kind.NONE }
        return when {
            host == "h1cloud.net" || host.endsWith(".h1cloud.net") ||
                host == "h1cloud.com" || host.endsWith(".h1cloud.com") -> Kind.H1CLOUD
            host == "vainahvpn-python-preview.onrender.com" -> Kind.PYTHON_RENDER
            host == "vainahvpnbot0.netlify.app" -> Kind.LEGACY_NETLIFY
            else -> Kind.OTHER_HTTPS
        }
    }

    fun label(kind: Kind): String = when (kind) {
        Kind.NONE -> "Адрес подписки отсутствует или не распознан."
        Kind.H1CLOUD -> "Источник: официальный домен H1Cloud."
        Kind.PYTHON_RENDER -> "Источник: Python/Render Vainah VPN."
        Kind.LEGACY_NETLIFY -> "Источник: старый сайт Vainah VPN на Netlify."
        Kind.OTHER_HTTPS -> "Источник: другой HTTPS-сервер подписки."
        Kind.DIRECT_KEY -> "Источник: локальный VLESS-ключ; HTTPS не используется."
    }
}
