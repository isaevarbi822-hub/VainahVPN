package app.vainah.vpn

import java.util.Locale

/**
 * Group only the TWO explicitly named Turkey entries already imported from H1Cloud.
 * Accept common separators, numbered labels and ordinary-space labels; never synthesize a
 * server, alter its VLESS URI, or imply LTE/transport connectivity.
 */
object TurkeyLteGroups {
    enum class Slot { ONE, IP }

    private val requested = Regex(
        "^(?:турция|turkey|türkiye|turkiye)(?:\\s*🇹🇷)?(?:\\s*[·•|#№\\-–—:]\\s*|\\s+)(1|ip)$",
        RegexOption.IGNORE_CASE
    )

    private fun normalized(label: String): String = label
        .trim().lowercase(Locale.ROOT)
        .replace(Regex("[\\p{Cntrl}]"), " ")
        .replace(Regex("\\s+"), " ")
        .removePrefix("🇹🇷").trim()

    /** Exact match: Turkey 1/IP, not Turkey 10, IP 2, LTE or a VLESS URL. */
    fun slot(label: String): Slot? =
        when (requested.matchEntire(normalized(label))?.groupValues?.get(1)) {
            "1" -> Slot.ONE
            "ip" -> Slot.IP
            else -> null
        }

    fun isPreferredLte(label: String): Boolean = slot(label) != null

    /** Use ONLY real imported nodes; no fabricated addresses or endpoint tags. */
    fun matchingIds(nodes: List<VainahNode>): Set<String> =
        nodes.asSequence()
            .filter { slot(it.label) != null }
            .map { ServerDirectory.identity(it.uri) }
            .toSet()
}
