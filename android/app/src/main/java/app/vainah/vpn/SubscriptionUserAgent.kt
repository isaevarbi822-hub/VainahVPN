package app.vainah.vpn

/**
 * Some subscription providers restrict response formats/access by User-Agent.
 * Allow only explicit, user-entered values approved for their subscription.
 * Never change the TLS trust policy or silently impersonate another client.
 */
object SubscriptionUserAgent {
    fun validate(raw: String): String? {
        val value = raw.trim()
        if (value.length !in 5..180 || !value[0].isLetterOrDigit()) return null
        if (!value.all { it.code in 32..126 }) return null
        // URL/token-looking strings should never be forwarded to an HTTP header.
        val normalized = value.lowercase(java.util.Locale.ROOT)
        if (listOf("://", "token=", "authorization:", "bearer ", "cookie:",
            "password=", "secret=").any { it in normalized }) return null
        return value
    }

    fun effective(userSpecified: String?, appVersion: String): String =
        userSpecified?.let(::validate) ?: "VainahVPN-Android/" + appVersion
}
