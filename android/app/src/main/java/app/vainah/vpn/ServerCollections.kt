package app.vainah.vpn

import java.util.Locale

/**
 * Visible collections use the user's actual H1Cloud/subscription node labels.
 *
 * A collection is not a new VPN endpoint, a special routing promise, or an
 * active network check. In particular, the "Белые списки" group only contains
 * subscription entries that the provider explicitly marked as such.
 */
enum class ServerCollection(val title: String) {
    ALL("Все"),
    RECOMMENDED("Рекомендуемые"),
    FAST("Быстрые"),
    GAMES("Игры"),
    STREAMING("Стриминг"),
    WHITELIST("Белые списки"),
    FAVORITES("Избранные"),
}

object ServerCollections {
    /** Only clean UI labels, never VLESS URIs or subscription credentials. */
    fun isWhiteListLabel(label: String): Boolean {
        val safe = label.lowercase(Locale.ROOT).trim()
        return listOf(
            "whitelist", "white-list", "white list", "white_list",
            "белый список", "белый-список", "белые списки", "белые-списки",
            "белых списков", "белого списка", "вайтлист", "вайт-лист",
            "lte-доступ", "lte доступ", "lte access", "lte_access",
            "доступ lte", "лте-доступ", "лте доступ"
        ).any(safe::contains) ||
            Regex("(^|[^a-zа-я])lte($|[^a-zа-я])").containsMatchIn(safe)
    }

    private fun hasTopic(label: String, tokens: List<String>): Boolean {
        val safe = label.lowercase(Locale.ROOT)
        return tokens.any(safe::contains)
    }

    fun filter(
        entries: List<ServerDirectoryEntry>,
        collection: ServerCollection,
    ): List<ServerDirectoryEntry> = entries.filter { entry ->
        when (collection) {
            ServerCollection.ALL -> true
            ServerCollection.RECOMMENDED -> entry.favorite || entry.measuredTcpMs != null
            ServerCollection.FAST -> entry.measuredTcpMs != null
            ServerCollection.GAMES -> hasTopic(
                entry.info.title, listOf("game", "gaming", "игр", "pubg", "киберспорт")
            )
            ServerCollection.STREAMING -> hasTopic(
                entry.info.title, listOf("stream", "стрим", "видео", "youtube")
            )
            ServerCollection.WHITELIST ->
                isWhiteListLabel(entry.info.title) || entry.manualWhitelist
            ServerCollection.FAVORITES -> entry.favorite
        }
    }

    /** Display a collection-specific truthful empty state. */
    fun emptyMessage(collection: ServerCollection, hasNodes: Boolean): String {
        if (!hasNodes) return "В подписке нет серверов. Добавь ссылку H1Cloud и обнови список."
        return when (collection) {
            ServerCollection.ALL -> "Не нашлось серверов по запросу. Проверь поиск."
            ServerCollection.RECOMMENDED ->
                "Нет избранных или измеренных серверов. Добавь ★ или проверь TCP-задержку."
            ServerCollection.FAST ->
                "Нет подтверждённых TCP-замеров. Запусти измерение без активного VPN."
            ServerCollection.GAMES ->
                "Серверов с отметкой «игры» в подписке нет. Мы не создаём их автоматически."
            ServerCollection.STREAMING ->
                "В подписке нет узлов с отметкой «стриминг». Доступность видеосервисов не проверена."
            ServerCollection.WHITELIST ->
                "В загруженной подписке нет помеченных LTE-узлов. " +
                    "Обнови конфигурацию H1Cloud или отметь существующие " +
                    "узлы вручную: пометка не включает LTE-доступ."
            ServerCollection.FAVORITES ->
                "Здесь будут серверы, которые ты отметишь звёздочкой ★."
        }
    }
}
