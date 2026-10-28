package app.vainah.vpn

import java.nio.charset.StandardCharsets
import java.util.Base64

/**
 * The Clerk publishable key is deliberately PUBLIC but must be from an actual
 * configured Clerk instance. A synthetic pk_test_* token is not authentication.
 * Never place a sk_* key in an Android build.
 */
object ClerkPublicKey {
    fun isConfigured(value: String): Boolean {
        val encoded = Regex("^pk_(?:test|live)_([A-Za-z0-9_=-]{12,512})$")
            .matchEntire(value)?.groupValues?.get(1) ?: return false
        return runCatching {
            val data = Base64.getUrlDecoder().decode(encoded)
            val hostAndMarker = String(data, StandardCharsets.US_ASCII)
            if (!hostAndMarker.endsWith("$")) return@runCatching false
            val host = hostAndMarker.dropLast(1)
            host.length in 4..253 &&
                Regex("^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])$").matches(host) &&
                host.contains('.') &&
                !host.contains("..")
        }.getOrDefault(false)
    }
}
