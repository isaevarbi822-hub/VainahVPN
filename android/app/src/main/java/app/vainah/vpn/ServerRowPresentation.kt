package app.vainah.vpn

import java.util.Locale

/**
 * Credential-free information for the visual server list.
 * Never renders the VLESS authority, UUID, query, SNI, host or public key.
 * Titles originate from the parsed subscription; no demo locations.
 */
data class ServerRowInfo(
    val title: String,
    val flag: String,
    val subtitle: String,
    val transport: String,
    val country: String?,
)

object ServerRowPresentation {
    private data class Country(
        val display: String,
        val flag: String,
        val aliases: List<String>,
    )

    private val countries = listOf(
        Country("Турция", "🇹🇷", listOf("турц", "turkey", "türkiye", "turkiye")),
        Country("Швейцария", "🇨🇭", listOf("швейцар", "switzerland", "schweiz", "suisse")),
        Country("Испания", "🇪🇸", listOf("испан", "spain", "espana", "españa")),
        Country("США", "🇺🇸", listOf("сша", "usa", "united states", "america")),
        Country("Албания", "🇦🇱", listOf("албани", "albania")),
        Country("Беларусь", "🇧🇾", listOf("беларус", "belarus")),
        Country("Литва", "🇱🇹", listOf("литва", "литвы", "lithuania")),
        Country("Молдова", "🇲🇩", listOf("молдов", "moldova")),
        Country("Финляндия", "🇫🇮", listOf("финлянд", "finland", "suomi")),
        Country("Польша", "🇵🇱", listOf("польш", "poland", "polska")),
        Country("Германия", "🇩🇪", listOf("герман", "germany", "deutschland")),
        Country("Швеция", "🇸🇪", listOf("швец", "sweden", "sverige")),
        Country("Норвегия", "🇳🇴", listOf("норвег", "norway", "norge")),
        Country("Нидерланды", "🇳🇱", listOf("нидерланд", "netherlands", "holland")),
        Country("Франция", "🇫🇷", listOf("франц", "france")),
        Country("Великобритания", "🇬🇧", listOf("британи", "united kingdom", "england", "london")),
        Country("Италия", "🇮🇹", listOf("итали", "italy")),
        Country("Австрия", "🇦🇹", listOf("австри", "austria")),
        Country("Чехия", "🇨🇿", listOf("чехи", "czech", "czechia")),
        Country("Латвия", "🇱🇻", listOf("латви", "latvia")),
        Country("Эстония", "🇪🇪", listOf("эстони", "estonia")),
        Country("Япония", "🇯🇵", listOf("япони", "japan")),
        Country("Сингапур", "🇸🇬", listOf("сингапур", "singapore"))
    )

    private fun cleanLabel(label: String, fallbackIndex: Int): String {
        // A subscription label is untrusted. It must not be used to render
        // credential-bearing URLs, hostname, SNI or UUID fragments.
        val cleaned = label.replace(Regex("[\\p{Cntrl}]"), " ")
            .trim().take(64)
        if (cleaned.isBlank() || cleaned.contains("://") ||
            cleaned.contains('@') || cleaned.contains('?') ||
            cleaned.contains('#') || cleaned.contains('=') ||
            Regex("[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-").containsMatchIn(cleaned)
        ) return "Локация $fallbackIndex"
        return cleaned
    }

    fun describe(node: VainahNode, index: Int): ServerRowInfo {
        val safe = cleanLabel(node.label, index + 1)
        val lower = safe.lowercase(Locale.ROOT)
        val country = countries.firstOrNull { c ->
            safe.contains(c.flag) || c.aliases.any { lower.contains(it) }
        }
        // Original suffixes such as LTE or IP are meaningful; keep the
        // subscriber's safe label. Country is a supplemental flag, not a
        // replacement for the individual endpoint name.
        val title = if (country != null) {
            val withoutEmoji = safe.replace(country.flag, "").trim()
            if (withoutEmoji.isBlank()) country.display else withoutEmoji
        } else safe
        val protocol = if (runCatching {
            VlessRealityConfig.outbound(node.uri)
        }.isSuccess) "VLESS / TCP / REALITY"
        else "Формат не подтверждён"
        return ServerRowInfo(
            title = title,
            flag = country?.flag ?: "🌐",
            subtitle = protocol,
            transport = if (protocol == "VLESS / TCP / REALITY") "tcp" else "unknown",
            country = country?.display
        )
    }

    /** Display all nodes, keeping actual subscription order and distinguishing identical names. */
    fun describeList(nodes: List<VainahNode>): List<ServerRowInfo> {
        val original = nodes.mapIndexed { index, node -> describe(node, index) }
        val totals = original.groupingBy { it.title }.eachCount()
        val seen = mutableMapOf<String, Int>()
        return original.map { info ->
            val count = (seen[info.title] ?: 0) + 1
            seen[info.title] = count
            if ((totals[info.title] ?: 0) > 1)
                info.copy(title = info.title + " · " + count)
            else info
        }
    }

    /** Only previously measured entry-point TCP delays may appear as numbers. */
    fun latency(observation: ServerTcpObservation?): String {
        if (observation == null) return "н/д"
        val ms = observation.takeIf {
            it.attempts == ServerTcpSelector.ATTEMPTS_PER_NODE &&
                it.successes >= 2
        }?.medianMs ?: return "н/д"
        return "TCP $ms мс"
    }
}
