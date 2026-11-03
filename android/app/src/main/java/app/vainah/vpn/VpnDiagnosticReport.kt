package app.vainah.vpn

/**
 * Sanitized Android link facts for troubleshooting. Null means unobservable,
 * never that a VPN route is conclusively broken.
 */
data class VpnNetworkFacts(
    val visible: Boolean? = null,
    // True also for multiple routes whose union captures every IP, not
    // only an explicit 0/0 or ::/0. This is routing metadata, not proof of
    // successful packet forwarding or absence of provider-side filtering.
    val ipv4DefaultRoute: Boolean? = null,
    val ipv6DefaultRoute: Boolean? = null,
    val dnsConfigured: Boolean? = null
)

/**
 * Support report with a credential-free schema. Never export subscription
 * URLs, node UUIDs, hostnames, tokens or raw IP addresses to the clipboard.
 */
object VpnDiagnosticReport {
    private val safeCode = Regex("^[a-z][a-z0-9_]{0,63}$")
    private val phases = setOf("off", "starting", "tun_ready", "online", "failed")

    private fun code(raw: String?): String =
        raw?.takeIf { safeCode.matches(it) } ?: "unknown"

    fun create(
        phase: String?,
        lastStage: String?,
        probeReason: String?,
        androidApiLevel: Int,
        serviceRunning: Boolean,
        networkFacts: VpnNetworkFacts? = null
    ): String {
        fun flag(value: Boolean?): String = when (value) {
            true -> "yes"
            false -> "no"
            null -> "unknown"
        }
        val safePhase = phase?.takeIf { it in phases } ?: "unknown"
        val safeApi = androidApiLevel.takeIf { it in 26..99 }?.toString() ?: "unknown"
        return listOf(
            "Vainah VPN Android diagnostic v1",
            "android_api=$safeApi",
            "phase=$safePhase",
            "service_running=${if (serviceRunning) "yes" else "no"}",
            "last_stage=${code(lastStage)}",
            "https_probe=${code(probeReason)}",
            "android_vpn_visible=${flag(networkFacts?.visible)}",
            "android_ipv4_default_route=${flag(networkFacts?.ipv4DefaultRoute)}",
            "android_ipv6_default_route=${flag(networkFacts?.ipv6DefaultRoute)}",
            "android_vpn_dns_configured=${flag(networkFacts?.dnsConfigured)}",
            "vpn_egress=not_verified_on_device"
        ).joinToString("\n")
    }
}
