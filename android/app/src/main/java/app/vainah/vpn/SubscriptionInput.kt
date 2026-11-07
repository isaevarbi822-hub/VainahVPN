package app.vainah.vpn

/**
 * An active H1Cloud user may receive either a subscription HTTPS URL or an
 * individual VLESS TCP REALITY key. Direct keys are parsed locally and never
 * submitted to a third-party URL.
 *
 * Both are secrets and are stored only through SecureSubscription/Keystore.
 */
object SubscriptionInput {
    fun validate(raw: String): String? {
        val value = raw.trim()
        if (value.isBlank() || value.length > 8192 ||
            value.any { it.isISOControl() || it.isWhitespace() }) return null
        if (value.startsWith("vless://")) {
            return value.takeIf {
                runCatching { VlessRealityConfig.outbound(value) }.isSuccess
            }
        }
        return SubscriptionLink.validate(value)
    }

    fun isDirectKey(value: String): Boolean = value.startsWith("vless://")
}
