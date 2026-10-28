package app.vainah.vpn

import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.util.Base64
import java.util.UUID

/** Credential-safe decoding of SUB and compatible Xray/sing-box JSON documents.
 * All URLs remain in memory. Unsupported REALITY transports are excluded.
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
        val supported = ArrayList<VainahNode>()
        for (url in urls) {
            if (url.length > 8192 || !url.startsWith("vless://")) continue
            if (runCatching { VlessRealityConfig.outbound(url) }.isFailure) continue
            supported.add(VainahNode(
                SubscriptionServers.displayName(url, supported.size + 1), url
            ))
            require(supported.size <= MAX_NODES) { "Too many supported servers" }
        }
        val unique = ServerListReconciler.unique(supported)
        require(unique.isNotEmpty()) { "No supported VLESS REALITY TCP servers" }
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
                            result.addAll(xrayLinks(item))
                        item.optString("type") == "vless" ->
                            singBoxLink(item)?.let { result.add(it) }
                        else -> {
                            val nested = item.optJSONArray("outbounds")
                            if (nested != null && nested.length() <= MAX_NODES) {
                                for (j in 0 until nested.length()) {
                                    val outbound = nested.optJSONObject(j) ?: continue
                                    if (outbound.optString("protocol") == "vless")
                                        result.addAll(xrayLinks(outbound))
                                    else if (outbound.optString("type") == "vless")
                                        singBoxLink(outbound)?.let { result.add(it) }
                                }
                            }
                            val link = item.optString("uri").takeIf { it.startsWith("vless://") }
                                ?: item.optString("link").takeIf { it.startsWith("vless://") }
                            if (link != null) result.add(link)
                        }
                    }
                }
            }
            require(result.size <= MAX_NODES) { "Too many subscription nodes" }
        }
        return result
    }

    private fun xrayLinks(item: JSONObject): List<String> {
        val stream = item.optJSONObject("streamSettings") ?: return emptyList()
        if (stream.optString("security") != "reality" ||
            stream.optString("network", "tcp") !in listOf("tcp", "raw")) return emptyList()
        val reality = stream.optJSONObject("realitySettings") ?: return emptyList()
        val sni = reality.optString("serverName")
        val pbk = reality.optString("publicKey")
        if (sni.isBlank() || pbk.isBlank()) return emptyList()
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
                    reality.optString("shortId"),
                    reality.optString("fingerprint", "chrome"),
                    user.optString("flow"), item.optString("tag")
                )?.let { result.add(it) }
                if (result.size > MAX_NODES) return emptyList()
            }
        }
        return result
    }

    private fun singBoxLink(item: JSONObject): String? {
        val transport = item.optJSONObject("transport")?.optString("type", "tcp")
        if (transport != null && transport !in listOf("tcp", "raw")) return null
        val tls = item.optJSONObject("tls") ?: return null
        val reality = tls.optJSONObject("reality") ?: return null
        if (!tls.optBoolean("enabled") || !reality.optBoolean("enabled")) return null
        return link(
            item.optString("uuid"), item.optString("server"),
            item.optInt("server_port"), tls.optString("server_name"),
            reality.optString("public_key"), reality.optString("short_id"),
            tls.optJSONObject("utls")?.optString("fingerprint", "chrome") ?: "chrome",
            item.optString("flow"), item.optString("tag")
        )
    }

    private fun link(
        uuid: String, host: String, port: Int, sni: String, pbk: String,
        sid: String, fp: String, flow: String, label: String
    ): String? {
        if (uuid.length > 64 || runCatching { UUID.fromString(uuid) }.isFailure ||
            host.isBlank() || host.length > 253 || port !in 1..65535 ||
            sni.isBlank() || sni.length > 253 || pbk.isBlank() || pbk.length > 256 ||
            fp.length > 80 || sid.length > 128 || flow.length > 128) return null
        val authority = if (host.contains(':') && !host.startsWith("[")) "[" + host + "]" else host
        fun enc(s: String) = URLEncoder.encode(s, "UTF-8")
        val query = buildList {
            add("security=reality")
            add("type=tcp")
            add("sni=" + enc(sni))
            add("pbk=" + enc(pbk))
            add("fp=" + enc(fp.ifBlank { "chrome" }))
            if (sid.isNotBlank()) add("sid=" + enc(sid))
            if (flow.isNotBlank()) add("flow=" + enc(flow))
        }.joinToString("&")
        val safeLabel = if (label.length in 1..80 &&
            !label.contains("://") && !label.contains('@') &&
            !label.contains('?') && !label.contains('#')) label
        else "VLESS REALITY"
        val raw = "vless://" + uuid + "@" + authority + ":" + port +
            "?" + query + "#" + enc(safeLabel)
        return raw.takeIf { runCatching { VlessRealityConfig.outbound(it) }.isSuccess }
    }
}
