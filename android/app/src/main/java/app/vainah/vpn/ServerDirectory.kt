package app.vainah.vpn

import java.security.MessageDigest
import java.util.Locale

/** Local server selection. No network requests or private VLESS strings in UI text. */
enum class ServerSort { SUBSCRIPTION, COUNTRY, MEASURED_TCP }

data class ServerDirectoryEntry(
    val index: Int,
    val info: ServerRowInfo,
    val favorite: Boolean,
    val measuredTcpMs: Int?,
)

object ServerDirectory {
    const val MAX_FAVORITES = 20

    /** A stable identifier, NOT the bearer credential itself. Encrypt when persisted. */
    fun identity(uri: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(
            uri.toByteArray(Charsets.UTF_8)
        )
        return digest.joinToString("") { "%02x".format(it.toInt() and 0xff) }
    }

    fun validId(value: String): Boolean =
        value.length == 64 && value.all { it in '0'..'9' || it in 'a'..'f' }

    fun view(
        nodes: List<VainahNode>,
        favorites: Set<String>,
        query: String,
        favoritesOnly: Boolean,
        sort: ServerSort,
        observations: List<ServerTcpObservation> = emptyList(),
    ): List<ServerDirectoryEntry> {
        val safeQuery = query.trim().take(60).lowercase(Locale.ROOT)
        val infos = ServerRowPresentation.describeList(nodes)
        val items = infos.mapIndexed { index, info ->
            val measurement = observations.firstOrNull { it.index == index }
            val measured = measurement?.takeIf {
                it.attempts == ServerTcpSelector.ATTEMPTS_PER_NODE &&
                    it.successes >= 2
            }?.medianMs
            ServerDirectoryEntry(
                index = index, info = info,
                favorite = identity(nodes[index].uri) in favorites,
                measuredTcpMs = measured,
            )
        }
        val filtered = items.filter { row ->
            (!favoritesOnly || row.favorite) &&
                (safeQuery.isEmpty() ||
                    row.info.title.lowercase(Locale.ROOT).contains(safeQuery) ||
                    row.info.country?.lowercase(Locale.ROOT)?.contains(safeQuery) == true ||
                    row.info.subtitle.lowercase(Locale.ROOT).contains(safeQuery))
        }
        return filtered.sortedWith(
            compareBy<ServerDirectoryEntry> { if (it.favorite) 0 else 1 }
                .thenBy {
                    when (sort) {
                        ServerSort.COUNTRY -> it.info.country?.lowercase(Locale.ROOT) ?: "яяяя"
                        else -> ""
                    }
                }
                .thenBy {
                    if (sort == ServerSort.MEASURED_TCP)
                        it.measuredTcpMs ?: Int.MAX_VALUE
                    else 0
                }
                .thenBy { it.index }
        )
    }
}
