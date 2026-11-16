package app.vainah.vpn

import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.util.Base64
import java.util.UUID

/** Credential-safe decoding of SUB and Xray/sing-box JSON documents.
 * Keep eligible but unsupported transports visible (never silently drop LTE nodes).
 * The VPN engine continues to reject connections it cannot actually run.
 */
object SubscriptionPayloadParser {
    private const val MAX_NODES = 50
    private const val MAX_BYTES = 262144

    fun nodes(body: String): List<VainahNode> {
        require(body.toByteArray(Charsets.UTF_8).size <= MAX_BYTES) {
            "Subscription payload too large"
        }
        val input = body.trim().removePrefix("\uFEFF").trim()
        require(input.isNotEmpty()) { "Empty subscription" }
        val urls = when {
            input.startsWith("{") || input.startsWith("[") -> jsonLinks(input)
            else -> {
                val raw = plainLinks(input)
                if (raw.isNotEmpty()) raw else {
                    val decoded = decodeBase64(input) ?: ""
                    if (decoded.startsWith("{") || decoded.startsWith("[")) jsonLinks(decoded)
                    else plainLinks(decoded)
                }
            }
        }
        val imported = ArrayList<VainahNode>()
        for (url in urls) {
            if (url.length > 8192 || !url.startsWith("vless://")) continue
            if (SubscriptionNodeSupport.inspect(url) == null) continue
            imported.add(VainahNode(
                SubscriptionServers.displayName(url, imported.size + 1), url
            ))
            require(imported.size <= MAX_NODES) { "Too many VLESS nodes" }
        }
        val unique = ServerListReconciler.unique(imported)
        require(unique.isNotEmpty()) { "No recognized VLESS TLS/REALITY nodes" }
        return unique
    }

    private fun plainLinks(input: String): List<String> =
        input.lines().map { it.trim() }.filter { it.startsWith("vless://") }

    private fun decodeBase64(input: String): String? {
        val compact = input.filterNot { it.isWhitespace() }
        if (compact.isEmpty() ||
            !compact.matches(Regex("[A-Za-z0-9+/_=-]+"))) return null
        for (decoder in listOf(Base64.getDecoder(), Base64.getUrlDecoder())) {
            val decoded = runCatching {
                String(decoder.decode(compact), Charsets.UTF_8).trim()
            }.getOrNull() ?: continue
            if (decoded.contains("vless://") || decoded.startsWith("{") ||
                decoded.startsWith("[")) return decoded
        }
        return null
    }

    private fun jsonLinks(source: String): List<String> {
        val root: Any = try {
            if (source.startsWith("{")) JSONObject(source) else JSONArray(source)
        } catch (_: Exception) {
            throw IllegalArgumentException("Unsupported JSON subscription")
        }
        val items = when (root) {
            is JSONArray -> root
            is JSONObject -> root.optJSONArray("outbounds")
                ?: root.optJSONArray("profiles")
                ?: root.optJSONArray("servers")
                ?: root.optJSONArray("nodes")
                ?: root.optJSONArray("links")
                ?: throw IllegalArgumentException("Unsupported JSON subscription")
            else -> throw IllegalArgumentException("Unsupported JSON subscription")
        }
        require(items.length() <= 200) { "Too many subscription entries" }
        val result = ArrayList<String>()
        for (i in 0 until items.length()) {
            when (val item = items.opt(i)) {
                is String -> if (item.startsWith("vless://")) result.add(item)
                is JSONObject -> {
                    when {
                        item.optString("protocol") == "vless" ->
                            result.addAll(xrayLinks(item).map { tagWhitelist(it, item) })
                        item.optString("type") == "vless" ->
                            singBoxLink(item)?.let { result.add(tagWhitelist(it, item)) }
                        else -> {
                            val nested = item.optJSONArray("outbounds")
                            if (nested != null && nested.length() <= MAX_NODES) {
                                for (j in 0 until nested.length()) {
                                    val outbound = nested.optJSONObject(j) ?: continue
                                    if (outbound.optString("protocol") == "vless")
                                        result.addAll(xrayLinks(outbound).map {
                                            tagWhitelist(it, outbound, item)
                                        })
                                    else if (outbound.optString("type") == "vless")
                                        singBoxLink(outbound)?.let {
                                            result.add(tagWhitelist(it, outbound, item))
                                        }
                                }
                            }
                            val link = item.optString("uri").takeIf { it.startsWith("vless://") }
                                ?: item.optString("link").takeIf { it.startsWith("vless://") }
                            if (link != null) result.add(tagWhitelist(link, item))
                        }
                    }
                }
            }
            require(result.size <= MAX_NODES) { "Too many subscription nodes" }
        }
        return result
    }

    /**
     * Some H1Cloud-compatible JSON exports carry group/category metadata in
     * separate fields rather than the VLESS link fragment. Only explicit
     * provider metadata can classify a node; the connection URI is unchanged
     * except for its harmless, readable fragment. It remains a real server.
     */
    private fun hasWhitelistMetadata(item: JSONObject): Boolean {
        for (key in listOf(
            "whitelist", "white_list", "is_whitelist", "isWhitelist",
            "isWhiteList", "whiteList",
            "lte_access", "lte_enabled", "is_lte", "lteAccess", "lteEnabled"
        )) {
            if (item.opt(key) == true) return true
        }
        val keys = listOf(
            "name", "label", "group", "groups", "category", "categories",
            "tags", "labels", "profile_group", "service_group", "features", "service_type"
        )
        for (key in keys) {
            when (val value = item.opt(key)) {
                is String -> if (ServerCollections.isWhiteListLabel(value)) return true
                is JSONArray -> for (index in 0 until minOf(value.length(), 50)) {
                    if (value.optString(index).let(ServerCollections::isWhiteListLabel))
                        return true
                }
            }
        }
        return listOf("metadata", "meta").any { key ->
            item.optJSONObject(key)?.let { nested ->
                // Shallow read only: never recurse through untrusted JSON.
                keys.any { field ->
                    val value = nested.optString(field)
                    ServerCollections.isWhiteListLabel(value)
                } || listOf("whitelist", "is_whitelist").any {
                    nested.opt(it) == true
                }
            } == true
        }
    }

    private fun tagWhitelist(
        link: String, item: JSONObject, parent: JSONObject? = null
    ): String {
        if (!hasWhitelistMetadata(item) &&
            (parent == null || !hasWhitelistMetadata(parent))) return link
        val label = SubscriptionServers.displayName(link, 1)
        if (ServerCollections.isWhiteListLabel(label)) return link
        // URL fragment is display-only. Do not modify REALITY parameters,
        // endpoints, UUID or subscription access tokens.
        val tagged = (label.take(44) + " · LTE-доступ")
        return link.substringBefore('#') + "#" +
            URLEncoder.encode(tagged, "UTF-8").replace("+", "%20")
    }

    private fun xrayLinks(item: JSONObject): List<String> {
        val stream = item.optJSONObject("streamSettings") ?: return emptyList()
        val security = stream.optString("security").lowercase()
        val network = stream.optString("network", "tcp").lowercase()
        if (security !in listOf("reality", "tls") ||
            network !in listOf("tcp", "raw", "grpc", "xhttp", "splithttp")) return emptyList()
        val reality = stream.optJSONObject("realitySettings")
        val tls = stream.optJSONObject("tlsSettings")
        val sni = if (security == "reality")
            reality?.optString("serverName").orEmpty()
        else tls?.optString("serverName").orEmpty()
        val pbk = reality?.optString("publicKey").orEmpty()
        if (security == "reality" && (sni.isBlank() || pbk.isBlank()))
            return emptyList()
        val transportSettings = if (network in listOf("xhttp", "splithttp"))
            stream.optJSONObject("xhttpSettings") ?: stream.optJSONObject("splithttpSettings")
        else null
        val path = transportSettings?.optString("path").orEmpty()
        val mode = transportSettings?.optString("mode").orEmpty()
        val host = transportSettings?.optString("host").orEmpty()
        val padding = transportSettings?.let { options ->
            options.optString("x_padding_bytes").ifBlank {
                options.optString("xPaddingBytes")
            }
        }.orEmpty()
        // Malformed options on one Xray node must not hide the other
        // valid servers in the same subscription.
        val xhttpExtra = if (transportSettings != null)
            runCatching { XhttpCompatibility.shareExtra(transportSettings) }
                .getOrElse { return emptyList() } else ""
        val serviceName = stream.optJSONObject("grpcSettings")?.optString("serviceName").orEmpty()
        val servers = item.optJSONObject("settings")?.optJSONArray("vnext")
            ?: return emptyList()
        if (servers.length() > MAX_NODES) return emptyList()
        val result = ArrayList<String>()
        for (index in 0 until servers.length()) {
            val server = servers.optJSONObject(index) ?: continue
            val users = server.optJSONArray("users") ?: continue
            for (userIndex in 0 until minOf(users.length(), MAX_NODES)) {
                val user = users.optJSONObject(userIndex) ?: continue
                link(
                    user.optString("id"), server.optString("address"),
                    server.optInt("port"), sni, pbk,
                    reality?.optString("shortId").orEmpty(),
                    reality?.optString("fingerprint", "chrome")
                        ?: tls?.optString("fingerprint", "chrome") ?: "chrome",
                    user.optString("flow"), item.optString("tag"),
                    security, network, path, serviceName, mode, host, padding,
                    xhttpExtra
                )?.let { result.add(it) }
                if (result.size > MAX_NODES) return emptyList()
            }
        }
        return result
    }

    private fun singBoxLink(item: JSONObject): String? {
        val transport = item.optJSONObject("transport")
        val network = transport?.optString("type", "tcp")?.lowercase() ?: "tcp"
        if (network !in listOf("tcp", "raw", "grpc", "xhttp", "splithttp"))
            return null
        val tls = item.optJSONObject("tls") ?: return null
        if (!tls.optBoolean("enabled")) return null
        val reality = tls.optJSONObject("reality")
        val security = if (reality?.optBoolean("enabled") == true) "reality" else "tls"
        val xhttpExtra = if (network in listOf("xhttp", "splithttp"))
            runCatching { XhttpCompatibility.shareExtra(transport) }
                .getOrNull() ?: return null
        else ""
        return link(
            item.optString("uuid"), item.optString("server"),
            item.optInt("server_port"), tls.optString("server_name"),
            reality?.optString("public_key").orEmpty(),
            reality?.optString("short_id").orEmpty(),
            tls.optJSONObject("utls")?.optString("fingerprint", "chrome") ?: "chrome",
            item.optString("flow"), item.optString("tag"),
            security, network, transport?.optString("path").orEmpty(),
            transport?.optString("service_name").orEmpty(),
            transport?.optString("mode").orEmpty(),
            transport?.optString("host").orEmpty(),
            transport?.let { options ->
                options.optString("x_padding_bytes").ifBlank {
                    options.optString("xPaddingBytes")
                }
            }.orEmpty(),
            xhttpExtra
        )
    }

    private fun link(
        uuid: String, host: String, port: Int, sni: String, pbk: String,
        sid: String, fp: String, flow: String, label: String,
        security: String, network: String, path: String, serviceName: String,
        mode: String, httpHost: String, padding: String,
        xhttpExtra: String = ""
    ): String? {
        if (uuid.length > 64 || runCatching { UUID.fromString(uuid) }.isFailure ||
            host.isBlank() || host.length > 253 || port !in 1..65535 ||
            sni.length > 253 || pbk.length > 256 ||
            (security == "reality" && (sni.isBlank() || pbk.isBlank())) ||
            fp.length > 80 || sid.length > 128 || flow.length > 128 ||
            path.length > 512 || serviceName.length > 256 ||
            mode.length > 24 || httpHost.length > 253 || padding.length > 30 ||
            xhttpExtra.length > 4096) return null
        val authority = if (host.contains(':') && !host.startsWith("[")) "[" + host + "]" else host
        fun enc(s: String) = URLEncoder.encode(s, "UTF-8")
        val query = buildList {
            add("security=" + enc(security))
            add("type=" + enc(network))
            if (sni.isNotBlank()) add("sni=" + enc(sni))
            if (pbk.isNotBlank()) add("pbk=" + enc(pbk))
            add("fp=" + enc(fp.ifBlank { "chrome" }))
            if (sid.isNotBlank()) add("sid=" + enc(sid))
            if (flow.isNotBlank()) add("flow=" + enc(flow))
            if (path.isNotBlank()) add("path=" + enc(path))
            if (serviceName.isNotBlank()) add("serviceName=" + enc(serviceName))
            if (mode.isNotBlank()) add("mode=" + enc(mode))
            if (httpHost.isNotBlank()) add("host=" + enc(httpHost))
            if (padding.isNotBlank()) add("x_padding_bytes=" + enc(padding))
            if (network in listOf("xhttp", "splithttp") && xhttpExtra.isNotBlank())
                add("extra=" + enc(xhttpExtra))
        }.joinToString("&")
        val safeLabel = if (label.length in 1..80 &&
            !label.contains("://") && !label.contains('@') &&
            !label.contains('?') && !label.contains('#')) label
        else "VLESS REALITY"
        val raw = "vless://" + uuid + "@" + authority + ":" + port +
            "?" + query + "#" + enc(safeLabel).replace("+", "%20")
        return raw.takeIf { SubscriptionNodeSupport.inspect(it) != null }
    }
}
