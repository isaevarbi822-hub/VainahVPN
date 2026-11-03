package app.vainah.vpn

import org.json.JSONObject

/** Metadata-only inspection. Does not store or expose UUIDs, keys or server hosts. */
object XrayProfileInspection {
    data class Summary(val tcp: Int, val grpc: Int, val xhttp: Int) {
        val total get() = tcp + grpc + xhttp
    }

    fun inspect(json: String): Summary {
        require(json.toByteArray(Charsets.UTF_8).size <= 1024 * 1024) { "JSON too large" }
        val root = JSONObject(json)
        val outbounds = root.optJSONArray("outbounds")
            ?: throw IllegalArgumentException("Expected Xray outbounds")
        require(outbounds.length() <= 128) { "Too many outbounds" }
        var tcp = 0; var grpc = 0; var xhttp = 0
        for (i in 0 until outbounds.length()) {
            val o = outbounds.optJSONObject(i) ?: continue
            if (o.optString("protocol") != "vless") continue
            val stream = o.optJSONObject("streamSettings") ?: continue
            if (stream.optString("security") != "reality") continue
            val reality = stream.optJSONObject("realitySettings") ?: continue
            if (reality.optString("publicKey").isBlank()) continue
            val network = stream.optString("network", "tcp")
            val servers = o.optJSONObject("settings")?.optJSONArray("vnext") ?: continue
            for (j in 0 until servers.length()) {
                val server = servers.optJSONObject(j) ?: continue
                if (server.optString("address").isBlank() ||
                    server.optInt("port") !in 1..65535 ||
                    (server.optJSONArray("users")?.length() ?: 0) == 0) continue
                when (network) {
                    "tcp" -> tcp++
                    "grpc" -> grpc++
                    "xhttp" -> xhttp++
                }
                require(tcp + grpc + xhttp <= 128) { "Too many profiles" }
            }
        }
        return Summary(tcp, grpc, xhttp)
    }
}
