package app.vainah.vpn

/**
 * Honest, offline audit of the two user-requested Turkey nodes. This does not
 * resolve hosts, contact servers, open an Android TUN or claim VPN connectivity.
 * Only imported entries are examined; URI, UUID, SNI, host and keys never leave
 * this function. Exposed diagnostic strings are from strict fixed allowlists.
 */
object TurkeyServerAudit {
    enum class Status(val code: String) {
        MISSING("not_found_by_label"),
        UNSUPPORTED("local_profile_rejected"),
        READY("locally_parseable_not_connected")
    }

    data class Entry(
        val slot: TurkeyLteGroups.Slot,
        val status: Status,
        val importedCount: Int,
        val rejection: String = "unknown",
    ) {
        val title: String get() = when (slot) {
            TurkeyLteGroups.Slot.ONE -> "Турция 1"
            TurkeyLteGroups.Slot.IP -> "Турция IP"
        }
        val headline: String get() = when (status) {
            Status.MISSING -> "Не найден под этим названием"
            Status.UNSUPPORTED -> "Параметры не приняты приложением"
            Status.READY -> "Формат распознан · VPN не проверен"
        }
        val explanation: String get() = when (status) {
            Status.MISSING -> "Точного совпадения названия нет в загруженных записях. " +
                "Проверь другие узлы Турции в списке и название в H1Cloud. " +
                "Приложение не создаёт недостающие серверы."
            Status.UNSUPPORTED -> "Один или несколько импортированных профилей не прошли " +
                "локальную проверку. Код: " + SubscriptionNodeSupport.safeRejectionCode(rejection) + ". " +
                "Обновление подписки не устраняет несовместимость ядра и формата."
            Status.READY -> "Есть локально распознаваемый профиль. Это ещё не проверка " +
                "VLESS/REALITY/XHTTP, DNS, внешнего IP или соединения в браузере."
        }
        val safeDiagnostic: String get() = when (status) {
            Status.MISSING -> Status.MISSING.code
            Status.READY -> Status.READY.code
            Status.UNSUPPORTED -> Status.UNSUPPORTED.code + "_" +
                SubscriptionNodeSupport.safeRejectionCode(rejection)
        }
    }

    fun inspect(nodes: List<VainahNode>): List<Entry> =
        TurkeyLteGroups.Slot.entries.map { slot ->
            val found = nodes.asSequence()
                .filter { TurkeyLteGroups.slot(it.label) == slot }
                .take(50).toList()
            when {
                found.isEmpty() -> Entry(slot, Status.MISSING, 0)
                found.any { SubscriptionNodeSupport.inspect(it.uri)?.connectable == true } ->
                    Entry(slot, Status.READY, found.size)
                else -> Entry(
                    slot, Status.UNSUPPORTED, found.size,
                    SubscriptionNodeSupport.safeRejectionCode(
                        SubscriptionNodeSupport.inspect(found.first().uri)?.rejectionCode
                    )
                )
            }
        }
}
