package app.vainah.vpn

import java.util.Base64
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.UUID

/** Browser OIDC handoff uses one-time PKCE S256, never bearer links in Intents. */
internal object NativeOAuthFlow {
    data class Pending(
        val flow: String,
        val provider: String,
        val verifier: String,
        val createdAt: Long
    )

    fun verifier(): String {
        val random = ByteArray(32)
        SecureRandom().nextBytes(random)
        return Base64.getUrlEncoder().withoutPadding().encodeToString(random)
    }

    fun challenge(verifier: String): String {
        require(verifier.matches(Regex("[A-Za-z0-9_-]{43,128}")))
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(verifier.toByteArray(Charsets.US_ASCII))
        return Base64.getUrlEncoder().withoutPadding().encodeToString(digest)
    }

    fun validFlow(value: String): Boolean = runCatching {
        value.length == 36 && UUID.fromString(value).toString() == value
    }.getOrDefault(false)

    fun validCode(value: String): Boolean =
        value.matches(Regex("[A-Za-z0-9_-]{32,128}"))

    /**
     * Never pick the first value of a repeated callback parameter.
     * Duplicate flow/code values can make the app and the callback producer
     * disagree about which authorization attempt is being completed.
     */
    fun validCallbackParameters(
        flowValues: List<String>,
        codeValues: List<String>
    ): Boolean =
        flowValues.size == 1 && codeValues.size == 1 &&
            validFlow(flowValues.single()) && validCode(codeValues.single())

    fun validPending(item: Pending?, now: Long = System.currentTimeMillis()): Boolean =
        item != null && item.provider in setOf("google", "telegram") &&
            validFlow(item.flow) &&
            item.verifier.matches(Regex("[A-Za-z0-9_-]{43,128}")) &&
            now >= item.createdAt && now - item.createdAt <= 600_000L
}
