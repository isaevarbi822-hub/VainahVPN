package app.vainah.vpn

/**
 * Allowlisted native cabinet routes. Nothing here accepts a URL, an arbitrary
 * path, a subscription bearer token, or an operator admin API endpoint.
 */
internal object CabinetServicePaths {
    private val ticketId = Regex("^[A-Za-z0-9_-]{18,30}$")

    private val reads = setOf(
        "/api/support/config",
        "/api/support/tickets",
        "/api/account/devices",
        "/api/account/devices/limits",
        "/api/account/reminder-preference"
    )

    private val writes = setOf(
        "/api/support/tickets",
        "/api/account/devices",
        "/api/account/reminder-preference"
    )

    fun messagePath(id: String): String? =
        if (ticketId.matches(id)) "/api/support/tickets/$id/messages" else null

    fun allowRead(path: String): Boolean =
        path in reads || isMessagePath(path)

    fun allowWrite(path: String): Boolean =
        path in writes || isMessagePath(path)

    private fun isMessagePath(path: String): Boolean =
        path.startsWith("/api/support/tickets/") &&
            path.endsWith("/messages") &&
            messagePath(
                path.removePrefix("/api/support/tickets/")
                    .removeSuffix("/messages")
            ) == path
}

/** Keep message privacy boundaries aligned with the existing Python API. */
internal object SupportDraftPolicy {
    private val privateLink = Regex(
        "(?i)(?:https?://|vless://|vmess://|trojan://|hysteria2?://|" +
            "ss://|subscription[_ -]?url\\s*[:=])"
    )

    fun safe(message: String, minLength: Int): Boolean =
        message.trim().length in minLength..1500 &&
            !privateLink.containsMatchIn(message)

    fun category(value: String): Boolean =
        value in setOf("connection", "payment", "account", "other")
}
