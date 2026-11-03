package app.vainah.vpn

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Subscription URL is secret. Encrypt on-device using Android Keystore AES-GCM.
 * NEVER send it to analytics, logs, arbitrary URLs or an unverified web view.
 */
class SecureSubscription(private val context: Context) {
    private val alias = "vainah_subscription_aes_v1"
    private val store = context.getSharedPreferences("vpn_secure_profile", Context.MODE_PRIVATE)

    private fun key(): SecretKey {
        val keystore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keystore.getKey(alias, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(
                alias,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
            ).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return generator.generateKey()
    }

    fun save(raw: String): Boolean {
        val url = SubscriptionInput.validate(raw) ?: return false
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val encrypted = cipher.doFinal(url.toByteArray(Charsets.UTF_8))
        val iv = Base64.encodeToString(cipher.iv, Base64.NO_WRAP)
        val data = Base64.encodeToString(encrypted, Base64.NO_WRAP)
        val previous = load()
        val editor = store.edit().putString("ciphertext", "$iv:$data")
        // Never show cached servers from another subscriber/account.
        if (previous != url) {
            editor.remove("server_cache_v1")
            // Different subscription host may not authorize the same
            // client identity. Never silently forward a custom UA to it.
            editor.remove("user_agent_ciphertext_v1")
        }
        return editor.commit()
    }

    fun load(): String? {
        val pair = store.getString("ciphertext", null)?.split(':', limit = 2)
            ?: return null
        if (pair.size != 2) return null
        return try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(
                Cipher.DECRYPT_MODE, key(),
                GCMParameterSpec(128, Base64.decode(pair[0], Base64.NO_WRAP))
            )
            SubscriptionInput.validate(String(
                cipher.doFinal(Base64.decode(pair[1], Base64.NO_WRAP)), Charsets.UTF_8
            ))
        } catch (_: Exception) {
            // A corrupted or invalidated Keystore key must not leak ciphertext.
            null
        }
    }

    /**
     * Cache only successfully parsed server URIs inside Android Keystore AES-GCM.
     * A cached node list is not an entitlement or proof of current availability.
     */
    fun saveServerCache(subscription: String, nodes: List<VainahNode>): Boolean {
        val link = SubscriptionInput.validate(subscription) ?: return false
        if (nodes.isEmpty() || nodes.size > 50 || nodes.any { it.uri.length > 8192 })
            return false
        if (load() != link) return false
        return runCatching {
            val body = org.json.JSONObject()
                .put("link", link)
                .put("nodes", org.json.JSONArray(nodes.map { it.uri }))
                .toString().toByteArray(Charsets.UTF_8)
            if (body.size > 262144) return false
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, key())
            val ciphertext = cipher.doFinal(body)
            val iv = Base64.encodeToString(cipher.iv, Base64.NO_WRAP)
            val encrypted = Base64.encodeToString(ciphertext, Base64.NO_WRAP)
            // Recheck before writing: user may have changed the subscription.
            if (load() != link) return false
            store.edit().putString("server_cache_v1", "$iv:$encrypted").commit()
        }.getOrDefault(false)
    }

    fun cachedServers(subscription: String): List<VainahNode> {
        val link = SubscriptionInput.validate(subscription) ?: return emptyList()
        if (load() != link) return emptyList()
        val pair = store.getString("server_cache_v1", null)?.split(':', limit = 2)
            ?: return emptyList()
        if (pair.size != 2) return emptyList()
        return runCatching {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(
                Cipher.DECRYPT_MODE, key(),
                GCMParameterSpec(128, Base64.decode(pair[0], Base64.NO_WRAP))
            )
            val clear = cipher.doFinal(Base64.decode(pair[1], Base64.NO_WRAP))
            if (clear.size > 262144) return emptyList()
            val payload = org.json.JSONObject(String(clear, Charsets.UTF_8))
            if (payload.optString("link") != link) return emptyList()
            val values = payload.optJSONArray("nodes") ?: return emptyList()
            if (values.length() !in 1..50) return emptyList()
            val uris = (0 until values.length()).map { values.getString(it) }
            if (uris.any { it.length > 8192 }) return emptyList()
            SubscriptionPayloadParser.nodes(uris.joinToString("\n"))
        }.getOrElse { emptyList() }
    }

    /** User-chosen User-Agent can contain a per-client ID: encrypt it as a secret. */
    fun saveUserAgent(raw: String): Boolean {
        val value = SubscriptionUserAgent.validate(raw) ?: return false
        if (load() == null) return false
        return runCatching {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, key())
            val encoded = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
            val iv = Base64.encodeToString(cipher.iv, Base64.NO_WRAP)
            val data = Base64.encodeToString(encoded, Base64.NO_WRAP)
            store.edit().putString("user_agent_ciphertext_v1", "$iv:$data").commit()
        }.getOrDefault(false)
    }

    fun userAgent(): String? {
        if (load() == null) return null
        val pair = store.getString("user_agent_ciphertext_v1", null)
            ?.split(':', limit = 2) ?: return null
        if (pair.size != 2) return null
        return runCatching {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(
                Cipher.DECRYPT_MODE, key(),
                GCMParameterSpec(128, Base64.decode(pair[0], Base64.NO_WRAP))
            )
            SubscriptionUserAgent.validate(
                String(cipher.doFinal(Base64.decode(pair[1], Base64.NO_WRAP)),
                    Charsets.UTF_8)
            )
        }.getOrNull()
    }

    fun resetUserAgent() {
        store.edit().remove("user_agent_ciphertext_v1").apply()
    }

    fun delete() {
        store.edit().remove("ciphertext").remove("server_cache_v1")
            .remove("user_agent_ciphertext_v1").apply()
    }
}
