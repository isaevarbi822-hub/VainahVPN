package app.vainah.vpn

import java.util.Locale

/**
 * UI-only LTE grouping explicitly chosen by the owner for TWO real
 * H1Cloud subscription entries. No server is synthesized or configured.
 * A label alone does not activate LTE privileges on the provider.
 */
object TurkeyLteGroups {
    private val preferredNode = Regex(
        "^(?:🇹🇷\\s*)?(?:турция|turkey|türkiye|turkiye)(?:\\s*[·•\\-–—:]\\s*|\\s+)(?:1|ip)$",
        RegexOption.IGNORE_CASE
    )

    private fun normalized(label: String): String {
        val safe = label.trim().lowercase(Locale.ROOT)
            .replace(Regex("[\\p{Cntrl}]"), " ")
            .replace(Regex("\\s+"), " ")
        return safe.removePrefix("🇹🇷").trim()
    }

    /** Match exactly Turkey · 1 and Turkey · IP, NOT Turkey · 10, 11 or 2. */
    fun isPreferredLte(label: String): Boolean {
        return preferredNode.matches(normalized(label))
    }

    /** Use only the labels of actual imported nodes (never manufacture URIs). */
    fun matchingIds(nodes: List<VainahNode>): Set<String> =
        nodes.asSequence()
            .filter { isPreferredLte(it.label) }
            .map { ServerDirectory.identity(it.uri) }
            .toSet()
}
