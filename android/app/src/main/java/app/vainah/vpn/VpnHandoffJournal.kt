package app.vainah.vpn

/**
 * Bounded, local-only history of Android's PHYSICAL network transitions.
 *
 * Contains no SSID, network ID, IP, VPN address, subscription, or timestamp.
 * A "validated" physical network is not proof of successful VPN traffic.
 * Data is encoded as a strict enum-only record for safe support reports.
 */
data class VpnHandoffEvent(
    val from: String,
    val to: String,
    val state: String,
    val validated: Boolean,
)

object VpnHandoffJournal {
    const val MAX_EVENTS = 12
    private val transports = setOf("none", "wifi", "cellular", "ethernet", "other")
    private val states = setOf(
        "underlay_available", "underlay_lost", "underlay_changed",
        "underlay_validation_changed"
    )

    fun safe(event: VpnHandoffEvent): Boolean =
        event.from in transports && event.to in transports &&
            event.state in states && event.from.length <= 8 && event.to.length <= 8

    fun parse(raw: String?): List<VpnHandoffEvent> =
        raw.orEmpty().take(2400).split(';').mapNotNull { encoded ->
            val fields = encoded.split(',')
            if (fields.size != 4) return@mapNotNull null
            val checked = when (fields[3]) {
                "1" -> true
                "0" -> false
                else -> return@mapNotNull null
            }
            val record = VpnHandoffEvent(fields[0], fields[1], fields[2], checked)
            record.takeIf(::safe)
        }.takeLast(MAX_EVENTS)

    fun append(raw: String?, event: VpnHandoffEvent): String {
        val clean = if (safe(event)) parse(raw) + event else parse(raw)
        return clean.takeLast(MAX_EVENTS).joinToString(";") {
            listOf(it.from, it.to, it.state, if (it.validated) "1" else "0")
                .joinToString(",")
        }
    }

    fun sanitizedReport(raw: String?): String =
        parse(raw).joinToString("|") {
            "${it.from}>${it.to}:${it.state}:${if (it.validated) "1" else "0"}"
        }.ifEmpty { "none" }
}
