package app.vainah.vpn

import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import java.net.URLDecoder
import java.util.UUID

/**
 * Build a sing-box VLESS outbound for TCP, gRPC and opt-in XHTTP using TLS
 * or REALITY. XHTTP requires a verified sing-box-lx native AAR and must never
 * be silently downgraded into HTTPUpgrade, WebSocket, or plain TCP.
 * Contains credentials: never log or display the returned JSON.
 * Not itself a VPN engine; libbox still needs to own the Android VPN TUN.
 */
object VlessRealityConfig {
    fun outbound(raw: String, resolvedAddress: String? = null): JSONObject {
        require(raw.length <= 8192) { "Invalid node" }
        val uri = URI(raw)
        require(uri.scheme == "vless" && uri.host != null && uri.port in 1..65535)
        val uuid = uri.rawUserInfo ?: throw IllegalArgumentException("Missing UUID")
        UUID.fromString(uuid)
        val params = uri.rawQuery.orEmpty().split('&').mapNotNull { entry ->
            val pos = entry.indexOf('=')
            if (pos < 0) null else {
                val key = URLDecoder.decode(entry.substring(0, pos), "UTF-8")
                val value = URLDecoder.decode(entry.substring(pos + 1), "UTF-8")
                key to value
            }
        }.toMap()
        val security = params["security"] ?: ""
        require(security in listOf("reality", "tls")) { "TLS or REALITY required" }
        val transport = params["type"] ?: "tcp"
        require(transport in listOf("tcp", "raw", "grpc", "xhttp", "splithttp")) {
            "Unsupported transport"
        }
        val sni = params["sni"]?.takeIf { it.isNotBlank() }
            ?: if (security == "tls") uri.host
            else throw IllegalArgumentException("Missing REALITY SNI")
        // ALPN is wire-relevant for XHTTP and TLS: Happ/Xray links may
        // explicitly select h2 or http/1.1. Ignoring it can change the
        // HTTP transport and cause a working profile to fail in libbox.
        val alpnRaw = params["alpn"].orEmpty()
        val alpnProtocols = if (alpnRaw.isBlank()) emptyList() else
            alpnRaw.split(',').map { it.trim() }.also { protocols ->
                require(protocols.size in 1..8 && protocols.all {
                    it.matches(Regex("[A-Za-z0-9./_-]{1,32}"))
                }) { "Invalid ALPN" }
            }
        val publicKey = params["pbk"]?.takeIf { it.isNotBlank() }
        if (security == "reality") require(!publicKey.isNullOrBlank()) {
            "Missing REALITY key"
        }
        val flow = params["flow"]?.takeIf { it.isNotBlank() }
        require(flow == null || transport in listOf("tcp", "raw")) {
            "VLESS Vision flow requires raw TCP"
        }
        require(flow == null || flow == "xtls-rprx-vision") {
            "Unsupported VLESS flow"
        }
        val serviceName = (params["serviceName"] ?: params["service_name"]).orEmpty()
        require(serviceName.length <= 256 && !serviceName.contains('\n') &&
            !serviceName.contains('\r')) { "Invalid gRPC service name" }
        // Only a missing/empty path gets the protocol default. A decoded
        // whitespace/control-only path must fail validation, not be hidden
        // by an ifBlank("/") fallback.
        val xhttpPath = params["path"]?.takeIf { it.isNotEmpty() } ?: "/"
        val xhttpHost = params["host"].orEmpty()
        val xhttpMode = params["mode"].orEmpty().ifBlank { "auto" }
        val padding = params["x_padding_bytes"].orEmpty()
        require(xhttpPath.length in 1..512 && xhttpPath.startsWith('/') &&
            !xhttpPath.contains('\n') && !xhttpPath.contains('\r')) {
            "Invalid XHTTP path"
        }
        require(xhttpHost.length <= 253 && !xhttpHost.contains('\n') &&
            !xhttpHost.contains('\r')) { "Invalid XHTTP host" }
        require(xhttpMode in listOf("auto", "packet-up", "stream-up", "stream-one")) {
            "Invalid XHTTP mode"
        }
        require(padding.isBlank() ||
            padding.matches(Regex("[0-9]{1,5}(-[0-9]{1,5})?"))) {
            "Invalid XHTTP padding"
        }
        return JSONObject().apply {
            put("type", "vless")
            put("tag", "vainah-selected")
            put("server", resolvedAddress ?: uri.host)
            put("server_port", uri.port)
            put("uuid", uuid)
            // Bootstrap domain resolution must not recurse into the VLESS tunnel.
            put("domain_resolver", "dns-bootstrap")
            flow?.let { put("flow", it) }
            if (transport == "grpc") put("transport", JSONObject().apply {
                put("type", "grpc")
                put("service_name", serviceName)
            })
            if (transport == "xhttp" || transport == "splithttp") {
                val xhttp = JSONObject().apply {
                    put("type", "xhttp")
                    put("mode", xhttpMode)
                    put("path", xhttpPath)
                    if (xhttpHost.isNotBlank()) put("host", xhttpHost)
                    if (padding.isNotBlank()) put("x_padding_bytes", padding)
                }
                // A shared Xray/Happ URI can put wire-critical options inside
                // URL-encoded extra JSON. Do not silently drop those settings.
                put("transport", XhttpCompatibility.enrich(params, xhttp))
            }
            put("tls", JSONObject().apply {
                put("enabled", true)
                put("server_name", sni)
                if (alpnProtocols.isNotEmpty()) put("alpn", JSONArray(alpnProtocols))
                put("utls", JSONObject().put("enabled", true)
                    .put("fingerprint", params["fp"]?.takeIf { it.isNotBlank() } ?: "chrome"))
                if (security == "reality") put("reality", JSONObject().apply {
                    put("enabled", true)
                    put("public_key", publicKey)
                    put("short_id", params["sid"].orEmpty())
                })
            })
        }
    }

    fun profile(node: String, resolvedAddress: String? = null): String = JSONObject().apply {
        put("log", JSONObject().put("level", "warn"))
        // Android TUN DNS is hijacked to this resolver. Queries to
        // 1.1.1.1 travel over HTTPS inside the VLESS outbound.
        put("dns", JSONObject().apply {
            put("servers", JSONArray()
                .put(JSONObject()
                    .put("type", "local")
                    .put("tag", "dns-bootstrap"))
                .put(JSONObject()
                    .put("type", "https")
                    .put("tag", "dns-via-vless")
                    .put("server", "1.1.1.1")
                    .put("server_port", 443)
                    .put("path", "/dns-query")
                    .put("detour", "vainah-selected")))
            put("final", "dns-via-vless")
            put("strategy", "prefer_ipv4")
        })
        put("inbounds", JSONArray().put(JSONObject().apply {
            put("type", "tun")
            put("tag", "vainah-tun")
            put("address", JSONArray().put("172.19.0.1/30").put("fd00:19::1/126"))
            // The DNS virtual addresses must exactly match the Android
            // VpnService.Builder DNS entries. Keep the route's hijack-dns
            // rule when setting explicit dns_address (sing-box 1.14).
            put("dns_address", JSONArray().put("172.19.0.2").put("fd00:19::2"))
            put("auto_route", true)
            put("dns_mode", "hijack")
        }))
        put("outbounds", JSONArray().put(outbound(node, resolvedAddress))
            .put(JSONObject().put("type", "direct").put("tag", "direct")))
        put("route", JSONObject().put("final", "vainah-selected")
            // Required in sing-box 1.14.0: every potential domain dialer,
            // including internal direct and DNS clients, needs an explicit
            // resolver. This is only for bootstrap; app DNS stays DoH-via-VLESS.
            .put("default_domain_resolver", "dns-bootstrap")
            .put("auto_detect_interface", true)
            .put("rules", JSONArray()
                // sing-box 1.14 explicitly requires hijack routing for custom
                // dns_address. Matching virtual IPs works even before the
                // traffic's protocol can be sniffed.
                .put(JSONObject().put("ip_cidr", JSONArray()
                    .put("172.19.0.2/32").put("fd00:19::2/128"))
                    .put("action", "hijack-dns"))
                // Intercept all remaining ordinary DNS (TCP and UDP port 53)
                // to avoid silently proxying plain DNS to physical resolvers.
                .put(JSONObject().put("port", 53)
                    .put("action", "hijack-dns"))))
    }.toString()
}
