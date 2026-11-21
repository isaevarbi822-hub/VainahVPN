package app.vainah.vpn

/**
 * Stable physical-network selection for the libbox underlay.
 *
 * NEVER includes the VPN/TUN as a candidate. A VALIDATED physical network
 * is preferred, but validation only proves Android's connectivity probe,
 * not VPN or REALITY availability. A healthy current network stays selected
 * during overlapping Wi-Fi and cellular callbacks to avoid flapping.
 */
data class UnderlayCandidate(
    val key: String,
    val validated: Boolean,
    val unmetered: Boolean,
    val transport: String
)

object UnderlaySelectionPolicy {
    private val transports = setOf("wifi", "cellular", "ethernet", "other")

    fun choose(
        previousKey: String?,
        candidates: Collection<UnderlayCandidate>
    ): UnderlayCandidate? {
        val eligible = candidates.filter {
            it.key.isNotBlank() && it.key.length <= 64 && it.transport in transports
        }.distinctBy { it.key }
        if (eligible.isEmpty()) return null

        val previous = eligible.firstOrNull { it.key == previousKey }
        if (previous?.validated == true) return previous

        val validated = eligible.filter { it.validated }
        if (validated.isNotEmpty()) {
            return validated.minWithOrNull(
                compareBy<UnderlayCandidate>(
                    { if (it.unmetered) 0 else 1 },
                    { when (it.transport) {
                        "ethernet" -> 0
                        "wifi" -> 1
                        "cellular" -> 2
                        else -> 3
                    } },
                    { it.key }
                )
            )
        }

        // When Android reports no validated network, preserve the last
        // physical interface rather than rapidly oscillating between peers.
        if (previous != null) return previous
        return eligible.minWithOrNull(
            compareBy<UnderlayCandidate>(
                { if (it.unmetered) 0 else 1 },
                { when (it.transport) {
                    "ethernet" -> 0
                    "wifi" -> 1
                    "cellular" -> 2
                    else -> 3
                } },
                { it.key }
            )
        )
    }

    fun transition(previous: String?, next: String?): String = when {
        previous == null && next == null -> "no_underlay"
        previous == null -> "underlay_available"
        next == null -> "underlay_lost"
        previous == next -> "underlay_unchanged"
        else -> "underlay_changed"
    }
}
