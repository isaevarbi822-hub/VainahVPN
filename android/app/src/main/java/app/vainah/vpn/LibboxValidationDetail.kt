package app.vainah.vpn

import java.util.Locale

/**
 * Native validation errors can contain private VLESS URLs, UUIDs and hosts.
 * Only fixed, allowlisted codes leave this class: never store raw exception text.
 * A field hint describes what the parser rejected, not why a VPN failed.
 */
internal object LibboxValidationDetail {
    private val fields = setOf(
        "dns_mode", "dns_address", "default_domain_resolver", "domain_resolver",
        "detour", "auto_route", "inbounds", "outbounds", "address", "route",
        "dns", "transport", "tls", "reality", "utls", "server_name",
        "server_port", "server", "path", "mode", "headers", "x_padding_bytes",
        "no_grpc_header", "sc_min_posts_interval_ms", "sc_max_each_post_bytes",
        "session_placement", "session_key", "session_table", "xmux"
    )
    private val allowedXhttpOptions = setOf(
        "headers", "x_padding_bytes", "no_grpc_header",
        "sc_max_each_post_bytes", "sc_min_posts_interval_ms",
        "session_placement", "session_key", "session_table", "session_length",
        "seq_placement", "seq_key",
        "uplink_data_placement", "uplink_data_key", "uplink_chunk_size",
        "uplink_http_method", "x_padding_obfs_mode", "x_padding_placement",
        "x_padding_key", "x_padding_header", "x_padding_method", "xmux"
    )

    fun safeOption(candidate: String?): String =
        candidate?.takeIf { it in allowedXhttpOptions } ?: "unknown"

    private val allowlisted = fields.map { "unknown_field_$it" }.toSet() +
        setOf("unsupported_xhttp", "native_config_rejected",
            LibboxValidationIsolation.TRANSPORT_EXTRAS,
            LibboxValidationIsolation.TRANSPORT,
            LibboxValidationIsolation.OUTBOUND,
            LibboxValidationIsolation.SHARED)

    private val unknownField = Regex(
        """(?i)\b(?:unknown|unrecognized|unsupported)\s+field\s*[:=]?\s*["']?([a-z][a-z0-9_]{0,48})"""
    )
    private val unsupportedXhttp = Regex(
        """(?i)(?:unknown|unsupported|unrecognized)\s+(?:transport|network)(?:\s+type)?\s*[:=]?\s*["']?xhttp\b"""
    )

    fun classify(message: String?): String {
        // The raw text is read in memory only; this function returns constants.
        val input = message.orEmpty().take(1600)
        val field = unknownField.find(input)?.groupValues?.getOrNull(1)
            ?.lowercase(Locale.ROOT)
        if (field != null && field in fields) return "unknown_field_$field"
        if (unsupportedXhttp.containsMatchIn(input)) return "unsupported_xhttp"
        return "native_config_rejected"
    }

    fun safeCode(candidate: String?): String =
        candidate?.takeIf { it in allowlisted } ?: "unknown"
}
