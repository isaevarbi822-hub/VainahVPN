package app.vainah.vpn

import java.net.URI

/**
 * Every sensitive cabinet action stays on the existing official HTTPS origin
 * (same website cookie/session for email, Google or Telegram login).
 * No bearer subscription URL, card details or auth token is passed via Intents.
 */
object CabinetNavigation {
    private const val HOST = "vainahvpn.onrender.com"
    private val paths = setOf(
        "account.html", "plans.html", "my-devices.html",
        "support-center.html", "notifications.html", "gifts.html"
    )

    fun url(page: String): String? =
        page.takeIf(paths::contains)?.let { "https://$HOST/$it" }

    fun isTrustedUrl(value: String): Boolean = runCatching {
        val uri = URI(value)
        uri.scheme.equals("https", true) &&
            uri.host.equals(HOST, true) &&
            uri.port == -1 && uri.userInfo == null &&
            uri.rawQuery == null && uri.rawFragment == null &&
            uri.path?.removePrefix("/") in paths
    }.getOrDefault(false)

    fun sections(): List<Pair<String, String>> = listOf(
        "Мой кабинет и подписка" to "account.html",
        "Продление и тарифы" to "plans.html",
        "Устройства" to "my-devices.html",
        "Поддержка и обращения" to "support-center.html",
        "Напоминания" to "notifications.html",
        "Подарочные карты" to "gifts.html"
    )
}
