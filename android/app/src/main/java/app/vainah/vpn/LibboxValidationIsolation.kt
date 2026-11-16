package app.vainah.vpn

import org.json.JSONObject

/**
 * Offline, bounded differential checks performed ONLY after a native
 * checkConfig failure. The candidate configs are never used for a connection.
 *
 * A rejected XHTTP option must never silently become a TCP or WebSocket VPN.
 * We only export a fixed result code, not a node, hostname, UUID, or exception.
 */
internal object LibboxValidationIsolation {
    const val UNKNOWN = "native_config_rejected"
    const val TRANSPORT_EXTRAS = "transport_extra_rejected"
    const val TRANSPORT = "transport_rejected"
    const val OUTBOUND = "outbound_rejected"
    const val SHARED = "shared_config_rejected"

    fun classify(
        actualConfig: String,
        check: (String) -> Unit
    ): String {
        val current = runCatching { JSONObject(actualConfig) }.getOrNull()
            ?: return UNKNOWN
        val selected = current.optJSONArray("outbounds")?.optJSONObject(0)
            ?: return UNKNOWN
        val transport = selected.optJSONObject("transport")

        fun accepted(update: (JSONObject) -> Unit): Boolean = runCatching {
            // A fresh clone is required for every experiment. No candidate
            // can accidentally mutate the original user profile.
            val root = JSONObject(actualConfig)
            val outbound = root.getJSONArray("outbounds").getJSONObject(0)
            update(outbound)
            check(root.toString())
        }.isSuccess

        // First isolate advanced XHTTP settings from the base transport.
        // Preserve only standard wire fields while testing validity; never
        // feed this probe config into the actual tunnel.
        if (transport?.optString("type") == "xhttp") {
            val basic = JSONObject().put("type", "xhttp")
            for (name in listOf("mode", "path", "host")) {
                if (transport.has(name)) basic.put(name, transport.get(name))
            }
            if (accepted { it.put("transport", basic) }) return TRANSPORT_EXTRAS
        }
        if (transport != null && accepted { it.remove("transport") }) {
            return TRANSPORT
        }
        // Isolate provider-specific VLESS credentials/TLS from shared
        // TUN/DNS/route settings by using an inert direct outbound.
        if (accepted {
                it.clearAndReplaceWithDirect()
            }) {
            return OUTBOUND
        }
        return SHARED
    }

    private fun JSONObject.clearAndReplaceWithDirect() {
        // Mutate the object owned by the freshly-cloned config only.
        val keys = keys().asSequence().toList()
        keys.forEach { remove(it) }
        put("type", "direct")
        put("tag", "vainah-selected")
    }
}
