package app.vainah.vpn

import org.json.JSONArray
import org.json.JSONObject

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
            require(value != null && value != JSONObject.NULL)
            chosen[target] = value
        }
        for ((key, value) in chosen) {
            when (key) {
                "headers" -> transport.put(key, validateHeaders(value))
                "xmux" -> {
                    require(value is JSONObject && value.toString().length <= 1024) {
                        "Invalid XHTTP xmux"
                    }
                    transport.put(key, value)
                }
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
