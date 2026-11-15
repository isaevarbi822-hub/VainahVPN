package app.vainah.vpn

import android.content.Context
import java.net.IDN
import java.util.Locale

/**
 * Explicit, opt-in domain routing exceptions for the native Android tunnel.
 *
 * This is independent of provider-labelled "Белые списки" servers and of
 * Android's per-app exclusion. Only safe hostnames can enter the route config.
 * A bypassed connection uses the ordinary network and is not VPN-protected;
 * DNS may still go via the VPN and encrypted DNS / IP-only traffic may not match.
 */
object DomainWhitelistPolicy {
    const val MAX_DOMAINS = 20

    fun canonical(value: String): String? {
        val raw = value.trim().lowercase(Locale.ROOT)
        if (raw.isEmpty() || raw.length > 253 || raw != value.trim().lowercase(Locale.ROOT) ||
            raw.any { it.isWhitespace() || it in "/:@?#*\\\\%" } ||
            raw.startsWith(".") || raw.endsWith(".") || ".." in raw
        ) return null

        val ascii = try {
            IDN.toASCII(raw, IDN.USE_STD3_ASCII_RULES).lowercase(Locale.ROOT)
        } catch (_: IllegalArgumentException) {
            return null
        }
        if (ascii.length !in 4..253 || ascii.none { it == '.' }) return null
        val labels = ascii.split('.')
        if (labels.size < 2 || labels.any { segment ->
                segment.length !in 1..63 ||
                    !segment.first().isLetterOrDigit() ||
                    !segment.last().isLetterOrDigit() ||
                    !segment.all { it in 'a'..'z' || it in '0'..'9' || it == '-' }
            }
        ) return null
        // Never route the entire internet via a naked public suffix such as
        // "com" or accept numeric-only names that can masquerade as addresses.
        if (labels.last().all(Char::isDigit)) return null
        if (ascii.matches(Regex("(\\d{1,3}\\.){3}\\d{1,3}"))) return null
        if (labels.first() == "localhost" || ascii == "local.host") return null
        return ascii
    }

    fun normalize(values: Collection<String>): Set<String> {
        if (values.size > MAX_DOMAINS) return emptySet()
        val clean = values.map { canonical(it) ?: return emptySet() }.toSortedSet()
        return if (clean.size <= MAX_DOMAINS) clean else emptySet()
    }

    fun effective(
        configured: Collection<String>,
        lockdownEnabled: Boolean,
    ): Set<String> = if (lockdownEnabled) emptySet() else normalize(configured)
}

object DomainWhitelistPreferences {
    private const val PREFERENCES = "vainah_domain_whitelist_v1"
    private const val KEY_DOMAINS = "direct_domains"

    fun read(context: Context): Set<String> = DomainWhitelistPolicy.normalize(
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
            .getStringSet(KEY_DOMAINS, emptySet()) ?: emptySet()
    )

    fun save(context: Context, values: Collection<String>): Boolean {
        val normalized = DomainWhitelistPolicy.normalize(values)
        if (normalized.size != values.mapNotNull(DomainWhitelistPolicy::canonical).toSet().size ||
            values.any { DomainWhitelistPolicy.canonical(it) == null }
        ) return false
        // Synchronous commit keeps a new VPN connection from using old rules.
        return context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
            .edit().putStringSet(KEY_DOMAINS, normalized).commit()
    }
}
