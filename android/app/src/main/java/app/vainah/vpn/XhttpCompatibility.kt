package app.vainah.vpn

import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener

/**
 * Preserve the supported Xray XHTTP wire options instead of silently
 * discarding the encoded `extra` object in shared VLESS profiles.
 * No credentials or private URLs are logged or surfaced to the user.
 */
internal object XhttpCompatibility {
    private val names = mapOf(
        "path" to "path", "host" to "host", "mode" to "mode",
        "xPaddingBytes" to "x_padding_bytes", "x_padding_bytes" to "x_padding_bytes",
        "noGRPCHeader" to "no_grpc_header", "no_grpc_header" to "no_grpc_header",
        "headers" to "headers",
        "scMaxEachPostBytes" to "sc_max_each_post_bytes",
        "sc_max_each_post_bytes" to "sc_max_each_post_bytes",
        "scMinPostsIntervalMs" to "sc_min_posts_interval_ms",
        "sc_min_posts_interval_ms" to "sc_min_posts_interval_ms",
        "sessionPlacement" to "session_placement",
        "session_placement" to "session_placement",
        "sessionKey" to "session_key", "session_key" to "session_key",
        "seqPlacement" to "seq_placement", "seq_placement" to "seq_placement",
        "seqKey" to "seq_key", "seq_key" to "seq_key",
        "sessionIDTable" to "session_table", "session_table" to "session_table",
        "sessionIDLength" to "session_length", "session_length" to "session_length",
        "uplinkDataPlacement" to "uplink_data_placement",
        "uplink_data_placement" to "uplink_data_placement",
        "uplinkDataKey" to "uplink_data_key", "uplink_data_key" to "uplink_data_key",
        "uplinkChunkSize" to "uplink_chunk_size", "uplink_chunk_size" to "uplink_chunk_size",
        "uplinkHTTPMethod" to "uplink_http_method",
        "uplink_http_method" to "uplink_http_method",
        "xPaddingObfsMode" to "x_padding_obfs_mode",
        "x_padding_obfs_mode" to "x_padding_obfs_mode",
        "xPaddingPlacement" to "x_padding_placement",
        "x_padding_placement" to "x_padding_placement",
        "xPaddingKey" to "x_padding_key", "x_padding_key" to "x_padding_key",
        "xPaddingHeader" to "x_padding_header", "x_padding_header" to "x_padding_header",
        "xPaddingMethod" to "x_padding_method", "x_padding_method" to "x_padding_method",
        "xmux" to "xmux"
    )
    private val harmlessServerOnly = setOf(
        "noSSEHeader", "no_sse_header", "scMaxConcurrentPosts",
        "sc_max_concurrent_posts", "serverMaxHeaderBytes",
        "server_max_header_bytes", "scMaxBufferedPosts",
        "sc_max_buffered_posts", "scStreamUpServerSecs",
        "sc_stream_up_server_secs"
    )

    /**
     * Xray exports put XHTTP-specific settings under xhttpSettings.extra,
     * while sing-box exports place them directly under transport.
     * Preserve both when converting subscription JSON into a VLESS link.
     */
    fun shareExtra(settings: JSONObject?): String {
        if (settings == null) return ""
        val captured = JSONObject()
        val nested = when (val raw = settings.opt("extra")) {
            is JSONObject -> raw
            is String -> if (raw.isBlank()) JSONObject() else JSONObject(raw)
            else -> JSONObject()
        }
        val fromNested = nested.keys()
        while (fromNested.hasNext()) {
            val name = fromNested.next()
            captured.put(name, nested.opt(name))
        }
        val direct = settings.keys()
        while (direct.hasNext()) {
            val name = direct.next()
            if (name == "extra" || name in setOf(
                    "type", "mode", "path", "host", "x_padding_bytes", "xPaddingBytes"
                )) continue
            if (name in names || name in harmlessServerOnly)
                captured.put(name, settings.opt(name))
        }
        if (captured.length() == 0) return ""
        val output = captured.toString()
        require(output.length <= 4096) { "XHTTP extra too large" }
        return output
    }

    private fun validateHeaders(value: Any): JSONObject {
        require(value is JSONObject && value.length() <= 16) {
            "Invalid XHTTP headers"
        }
        val sanitized = JSONObject()
        val names = value.keys()
        while (names.hasNext()) {
            val name = names.next()
            require(name.matches(Regex("[A-Za-z0-9-]{1,64}")) &&
                !name.equals("Host", ignoreCase = true)) {
                "Invalid XHTTP header name"
            }
            val v = value.opt(name)
            val fields = when (v) {
                is String -> listOf(v)
                is JSONArray -> (0 until v.length()).map { v.optString(it) }
                else -> throw IllegalArgumentException("Invalid XHTTP header value")
            }
            require(fields.size in 1..8 &&
                fields.all { it.length <= 512 && it.none { c -> c == '\r' || c == '\n' } }) {
                "Invalid XHTTP header value"
            }
            sanitized.put(name, if (v is String) v else JSONArray(fields))
        }
        require(sanitized.toString().length <= 3072) { "XHTTP headers too large" }
        return sanitized
    }

    // Xray JSON uses camelCase for XMUX; the pinned sing-box-lx 1.14.4
    // parser expects snake_case. Preserve each field's value and meaning.
    // Unknown knobs must fail closed; dropping them can change the wire shape.
    private val xmuxNames = mapOf(
        "maxConcurrency" to "max_concurrency",
        "max_concurrency" to "max_concurrency",
        "maxConnections" to "max_connections",
        "max_connections" to "max_connections",
        "cMaxReuseTimes" to "c_max_reuse_times",
        "c_max_reuse_times" to "c_max_reuse_times",
        "hMaxRequestTimes" to "h_max_request_times",
        "h_max_request_times" to "h_max_request_times",
        "hMaxReusableSecs" to "h_max_reusable_secs",
        "h_max_reusable_secs" to "h_max_reusable_secs",
        "hKeepAlivePeriod" to "h_keep_alive_period",
        "h_keep_alive_period" to "h_keep_alive_period"
    )

    private fun normalizeXmuxRange(value: Any): String {
        // Match the pinned core's XmuxRange decoder and parseRange: empty
        // strings are unset, arrays have one or two integers, bounds may be
        // reversed, and surrounding whitespace is insignificant. Keep ""
        // distinct from "0": only an entirely unset section gets defaults.
        val parts = when (value) {
            is String -> {
                val trimmed = value.trim()
                if (trimmed.isEmpty()) return ""
                trimmed.split('-').map { it.trim() }
            }
            is Number -> listOf(value.toString())
            is JSONArray -> {
                require(value.length() in 1..2) { "Invalid XHTTP xmux range" }
                (0 until value.length()).map { i ->
                    val part = value.opt(i)
                    require(part is Number) { "Invalid XHTTP xmux range" }
                    part.toString()
                }
            }
            else -> throw IllegalArgumentException("Invalid XHTTP xmux range")
        }
        require(parts.size in 1..2 && parts.all {
            it.matches(Regex("[0-9]{1,10}"))
        }) { "Invalid XHTTP xmux range" }
        val bounds = parts.map {
            // A single bound must also fit Go's int on 32-bit Android ABIs.
            // Never truncate a fractional Number or pass overflowing strings.
            val number = it.toLongOrNull()
            require(number != null && number in 0..Int.MAX_VALUE.toLong()) {
                "Invalid XHTTP xmux range"
            }
            number
        }
        return if (bounds.size == 1) bounds.single().toString()
            else "${bounds.min()}-${bounds.max()}"
    }

    private fun normalizeXmux(value: Any): JSONObject {
        require(value.toString().length <= 1024) { "XHTTP xmux too large" }
        // Some subscription serializers encode nested options as JSON text,
        // just as xhttpSettings.extra itself may be JSON text. Decode one
        // object only; never discard malformed/unknown fields or recurse.
        val settings = when (value) {
            is JSONObject -> value
            is String -> try {
                val parser = JSONTokener(value)
                val parsed = parser.nextValue()
                require(parsed is JSONObject && parser.nextClean() == '\u0000')
                parsed
            } catch (_: Exception) {
                throw IllegalArgumentException("Invalid XHTTP xmux JSON")
            }
            else -> throw IllegalArgumentException("Invalid XHTTP xmux type")
        }
        // Count aliases only after reading their names, so an unknown seventh
        // field gets an accurate error instead of the old generic rejection.
        require(settings.length() <= 12) { "Too many XHTTP xmux fields" }
        val result = JSONObject()
        val keys = settings.keys()
        while (keys.hasNext()) {
            val source = keys.next()
            val dest = xmuxNames[source] ?: throw IllegalArgumentException(
                "Unsupported XHTTP xmux setting"
            )
            require(!result.has(dest)) { "Duplicate XHTTP xmux setting" }
            val raw = settings.opt(source)
            require(raw != null && raw != JSONObject.NULL) {
                if (dest == "h_keep_alive_period") "Invalid XHTTP xmux keepalive"
                else "Invalid XHTTP xmux range"
            }
            if (dest == "h_keep_alive_period") {
                val period = when (raw) {
                    is Int -> raw
                    is Long -> raw.takeIf { it in -86400L..86400L }?.toInt()
                    is String -> raw.takeIf { it.matches(Regex("-?[0-9]{1,5}")) }
                        ?.toIntOrNull()
                    else -> null
                }
                require(period != null && period in -86400..86400) {
                    "Invalid XHTTP xmux keepalive"
                }
                result.put(dest, period)
            } else {
                result.put(dest, normalizeXmuxRange(raw))
            }
        }
        // Xray rejects max_connections together with max_concurrency only
        // when BOTH upper bounds are positive. A configured 0 or "0-0"
        // means no active limit, and is a legitimate Xray export.
        // Rejecting mere presence of both fields blocked valid H1Cloud nodes.
        fun upperBound(name: String): Long {
            // All supported input forms now share sorted, integral bounds.
            return result.optString(name).substringAfterLast('-').toLongOrNull() ?: 0
        }
        require(!(upperBound("max_concurrency") > 0 &&
            upperBound("max_connections") > 0)) {
            "Conflicting XHTTP xmux limits"
        }
        return result
    }

    fun enrich(query: Map<String, String>, transport: JSONObject): JSONObject {
        val extraRaw = query["extra"]
        require(extraRaw == null || extraRaw.length <= 4096) { "XHTTP extra too large" }
        val extra = if (extraRaw.isNullOrBlank()) JSONObject()
            else try { JSONObject(extraRaw) } catch (_: Exception) {
                throw IllegalArgumentException("Invalid XHTTP extra")
            }
        require(extra.length() <= 48) { "Too many XHTTP options" }

        val chosen = LinkedHashMap<String, Any>()
        // Flat URI values are valid; Xray's explicit extra object takes priority.
        for (key in listOf(
            "path", "host", "mode", "xPaddingBytes", "x_padding_bytes",
            "noGRPCHeader", "no_grpc_header",
            "scMaxEachPostBytes", "scMinPostsIntervalMs"
        )) {
            val raw = query[key] ?: continue
            val target = names[key] ?: continue
            chosen[target] = when (target) {
                "no_grpc_header" -> when (raw) {
                    "true", "1" -> true
                    "false", "0" -> false
                    else -> throw IllegalArgumentException("Invalid noGRPCHeader")
                }
                else -> raw
            }
        }
        val keys = extra.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            if (key in harmlessServerOnly) continue
            // Downlink transport settings are not supported by the bundled core.
            // Refusing to connect is safer than silently changing their wire shape.
            val target = names[key] ?: throw IllegalArgumentException(
                "Unsupported XHTTP option"
            )
            val value = extra.opt(key)
            // A null optional XMUX section selects native defaults, just like
            // an absent section. Do not turn it into explicit zero limits.
            if (target == "xmux" && value == JSONObject.NULL) continue
            require(value != null && value != JSONObject.NULL)
            chosen[target] = value
        }
        for ((key, value) in chosen) {
            when (key) {
                "headers" -> transport.put(key, validateHeaders(value))
                "xmux" -> transport.put(key, normalizeXmux(value))
                "no_grpc_header", "x_padding_obfs_mode" -> {
                    require(value is Boolean) { "Invalid XHTTP boolean" }
                    transport.put(key, value)
                }
                "path" -> {
                    require(value is String && value.length in 1..512 &&
                        value.startsWith('/') && !value.contains('\r') && !value.contains('\n')) {
                        "Invalid XHTTP path"
                    }
                    transport.put(key, value)
                }
                "mode" -> {
                    require(value is String &&
                        value in setOf("auto", "packet-up", "stream-up", "stream-one")) {
                        "Invalid XHTTP mode"
                    }
                    transport.put(key, value)
                }
                "host" -> {
                    require(value is String && value.length <= 253 &&
                        !value.contains('\r') && !value.contains('\n')) {
                        "Invalid XHTTP host"
                    }
                    transport.put(key, value)
                }
                else -> {
                    require((value is String && value.length <= 128 &&
                        value.none { it == '\r' || it == '\n' }) ||
                        (value is Number && value.toLong() in 0..100_000_000L) ||
                        (value is JSONArray && value.length() == 2)) {
                        "Invalid XHTTP option value"
                    }
                    transport.put(key, value)
                }
            }
        }
        return transport
    }
}
