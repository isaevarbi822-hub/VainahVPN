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
/** Only system-observed physical network class; not an IP or VPN proof. */
data class VpnUnderlayFacts(
    val transport: String? = null,
    val validated: Boolean? = null,
    val transitions: Int? = null,
)

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
        networkFacts: VpnNetworkFacts? = null,
        underlay: VpnUnderlayFacts? = null,
        handoffEvents: List<VpnHandoffEvent> = emptyList(),
        recoveryCode: String? = null,
        failureCode: String? = null,
        routeScanPending: Boolean = false,
        libboxDetail: String? = null,
        nativeCore: String? = null,
        selectedTransport: String? = null,
        selectedSecurity: String? = null,
        libboxRejectedOption: String? = null,
        profileCheckTransport: String? = null,
        profileCheckSecurity: String? = null,
        profileCheckRejection: String? = null,
        turkeyAudit: List<TurkeyServerAudit.Entry> = emptyList()
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
            "app_version=${BuildConfig.VERSION_NAME}",
            "app_version_code=${BuildConfig.VERSION_CODE}",
            "native_xhttp_enabled=${if (BuildConfig.VAINAH_XHTTP_ENGINE_ENABLED) "yes" else "no"}",
            "android_api=$safeApi",
            "phase=$safePhase",
            "service_running=${if (serviceRunning) "yes" else "no"}",
            "last_stage=${code(lastStage)}",
            "https_probe=${code(probeReason)}",
            "vpn_route_check=${when {
                networkFacts != null -> "completed"
                routeScanPending -> "in_progress"
                else -> "not_run"
            }}",
            "android_vpn_visible=${flag(networkFacts?.visible)}",
            "android_ipv4_default_route=${flag(networkFacts?.ipv4DefaultRoute)}",
            "android_ipv6_default_route=${flag(networkFacts?.ipv6DefaultRoute)}",
            "android_vpn_dns_configured=${flag(networkFacts?.dnsConfigured)}",
            "underlay_type=${underlay?.transport?.takeIf {
                it in setOf("wifi","cellular","ethernet","other","none")
            } ?: "unknown"}",
            "underlay_validated=${flag(underlay?.validated)}",
            "underlay_switches=${underlay?.transitions?.takeIf {
                it in 0..9999
            }?.toString() ?: "unknown"}",
            "underlay_history=${VpnHandoffJournal.sanitized(handoffEvents)}",
            "underlay_recovery=${recoveryCode?.takeIf { it in setOf(
                "vpn_off", "underlay_long_outage", "underlay_brief_outage",
                "underlay_unvalidated", "underlay_restored_after_outage",
                "underlay_available"
            ) } ?: "unknown"}",
            "selected_transport=${selectedTransport?.takeIf {
                it in setOf("tcp", "grpc", "xhttp", "unknown")
            } ?: "unknown"}",
            "selected_security=${selectedSecurity?.takeIf {
                it in setOf("tls", "reality", "unknown")
            } ?: "unknown"}",
            "last_profile_check_transport=${profileCheckTransport?.takeIf {
                it in setOf("tcp", "grpc", "xhttp")
            } ?: "unknown"}",
            "last_profile_check_security=${profileCheckSecurity?.takeIf {
                it in setOf("tls", "reality")
            } ?: "unknown"}",
            "last_profile_check_result=${SubscriptionNodeSupport.safeRejectionCode(profileCheckRejection)}",
            "turkey_1_local_profile=${turkeyAudit.firstOrNull {
                it.slot == TurkeyLteGroups.Slot.ONE
            }?.safeDiagnostic ?: "unknown"}",
            "turkey_ip_local_profile=${turkeyAudit.firstOrNull {
                it.slot == TurkeyLteGroups.Slot.IP
            }?.safeDiagnostic ?: "unknown"}",
            "engine_failure=${VpnFailureAdvisor.sanitizedCode(failureCode)}",
            "libbox_validation_detail=${LibboxValidationDetail.safeCode(libboxDetail)}",
            "libbox_rejected_option=${LibboxValidationDetail.safeOption(libboxRejectedOption)}",
            "libbox_native_core=${nativeCore?.takeIf {
                it in setOf("lx_1_14_4_35", "lx_other", "non_lx_core", "unknown")
            } ?: "unknown"}",
            "vpn_egress=not_verified_on_device"
        ).joinToString("\n")
    }
}
