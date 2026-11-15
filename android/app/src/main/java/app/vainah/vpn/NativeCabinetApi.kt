package app.vainah.vpn

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.net.URL
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.net.ssl.HttpsURLConnection

/**
 * Server-issued HttpOnly email session, separately encrypted with Android
 * Keystore. Never persist a raw token, put it in URL, expose in a report,
 * or send it to any host except the exact official HTTPS origin.
 */
internal class NativeCabinetSession(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(
        "vainah_native_cabinet_v1", Context.MODE_PRIVATE
    )
    private val alias = "vainah_cabinet_aes_gcm_v1"
    private val emailCookie = "__Host-vainah_email_session"
    private val telegramCookie = "__Host-vainah_session"
    private val sessionPattern = Regex("[A-Za-z0-9_-]{20,1500}\\.[0-9a-f]{64}")

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val existing = store.getKey(alias, null) as? SecretKey
        if (existing != null) return existing
        val generator = KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore"
        )
        generator.init(KeyGenParameterSpec.Builder(alias,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setKeySize(256)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .build())
        return generator.generateKey()
    }

    private fun seal(prefix: String, text: String) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val ciphertext = cipher.doFinal(text.toByteArray(StandardCharsets.UTF_8))
        check(prefs.edit()
            .putString(prefix + "_iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .putString(prefix + "_sealed", Base64.encodeToString(ciphertext, Base64.NO_WRAP))
            .commit())
    }

    private fun unseal(prefix: String): String? = runCatching {
        // Old 2.0 installs stored the email session under "iv" and "sealed".
        val iv = prefs.getString(prefix + "_iv", null)
            ?: if (prefix == "auth") prefs.getString("iv", null) else null
            ?: return null
        val content = prefs.getString(prefix + "_sealed", null)
            ?: if (prefix == "auth") prefs.getString("sealed", null) else null
            ?: return null
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(
            128, Base64.decode(iv, Base64.NO_WRAP)))
        String(cipher.doFinal(Base64.decode(content, Base64.NO_WRAP)),
            StandardCharsets.UTF_8)
    }.getOrNull()

    fun save(session: String) = saveSession(emailCookie, session)

    fun saveSession(cookie: String, session: String) {
        require(cookie == emailCookie || cookie == telegramCookie)
        require(sessionPattern.matches(session))
        seal("auth", cookie + "\n" + session)
        prefs.edit().remove("iv").remove("sealed").apply()
    }

    fun readAuth(): Pair<String, String>? {
        val text = unseal("auth") ?: return null
        val index = text.indexOf('\n')
        // Backward compatible with the original native email login.
        val cookie = if (index < 0) emailCookie else text.substring(0, index)
        val session = if (index < 0) text else text.substring(index + 1)
        return if ((cookie == emailCookie || cookie == telegramCookie) &&
            sessionPattern.matches(session)) cookie to session else null
    }

    fun read(): String? = readAuth()?.second

    fun savePending(pending: NativeOAuthFlow.Pending) {
        require(NativeOAuthFlow.validPending(pending))
        seal("oauth", listOf(pending.flow, pending.provider,
            pending.verifier, pending.createdAt.toString()).joinToString("\n"))
    }

    fun pending(): NativeOAuthFlow.Pending? {
        val parts = unseal("oauth")?.split("\n") ?: return null
        if (parts.size != 4) return null
        val item = NativeOAuthFlow.Pending(
            parts[0], parts[1], parts[2], parts[3].toLongOrNull() ?: return null
        )
        if (!NativeOAuthFlow.validPending(item)) {
            clearPending()
            return null
        }
        return item
    }

    fun clearPending() {
        prefs.edit().remove("oauth_iv").remove("oauth_sealed").apply()
    }

    fun clear() {
        prefs.edit().remove("auth_iv").remove("auth_sealed")
            .remove("iv").remove("sealed").apply()
    }
}

/** Same-origin, no-redirect, no-cleartext native JSON requests. */
internal class NativeCabinetApi(context: Context) {
    private val session = NativeCabinetSession(context)
    private val emailCookie = "__Host-vainah_email_session"
    private val telegramCookie = "__Host-vainah_session"
    private val accepted = setOf(
        "/api/site/tariffs", "/api/shop/config",
        "/api/trial/config", "/api/trial/status",
        "/api/email-auth/config", "/api/email-auth/account",
        "/api/google/config", "/api/telegram-oidc/config",
        "/api/mobile-auth/config", "/api/telegram/account",
        "/api/account/overview"
    )
    private val writes = setOf(
        "/api/email-auth/request", "/api/email-auth/verify",
        "/api/email-auth/logout", "/api/trial/claim",
        "/api/mobile-auth/start", "/api/mobile-auth/exchange"
    )

    data class Reply(val status: Int, val json: JSONObject?) {
        val ok: Boolean get() = status in 200..299
    }

    fun hasSession(): Boolean = session.readAuth() != null
    fun authCookieName(): String? = session.readAuth()?.first
    fun forgetSession() = session.clear()
    fun saveOAuthPending(item: NativeOAuthFlow.Pending) = session.savePending(item)
    fun pendingOAuth(): NativeOAuthFlow.Pending? = session.pending()
    fun clearOAuthPending() = session.clearPending()

    fun get(path: String): Reply {
        require(path in accepted)
        return request(path, null)
    }

    fun post(path: String, body: JSONObject = JSONObject()): Reply {
        require(path in writes)
        return request(path, body)
    }

    private fun request(path: String, payload: JSONObject?): Reply {
        val address = URL(NativeCabinetCatalog.API_ORIGIN + path)
        require(address.protocol == "https" &&
            address.host == "vainahvpn-python-preview.onrender.com"
            && address.port == -1)
        val conn = address.openConnection() as HttpsURLConnection
        conn.instanceFollowRedirects = false
        conn.connectTimeout = 9_000
        conn.readTimeout = 9_000
        conn.useCaches = false
        conn.setRequestProperty("Accept", "application/json")
        conn.setRequestProperty("User-Agent", "VainahVPN-Android-NativeCabinet")
        session.readAuth()?.let { (name, token) ->
            conn.setRequestProperty("Cookie", "$name=$token")
        }
        try {
            if (payload != null) {
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.setRequestProperty("Origin", NativeCabinetCatalog.API_ORIGIN)
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                val data = payload.toString().toByteArray(StandardCharsets.UTF_8)
                require(data.size <= 8_192)
                conn.outputStream.use { it.write(data) }
            }
            val status = conn.responseCode
            if (path == "/api/email-auth/verify" && status == 200) {
                val cookie = conn.headerFields.entries.asSequence()
                    .filter { it.key?.equals("Set-Cookie", ignoreCase = true) == true }
                    .flatMap { it.value.asSequence() }
                    .firstOrNull { it.startsWith("$emailCookie=") }
                    ?.substringAfter("=")?.substringBefore(";")
                if (cookie != null) session.save(cookie)
            }
            // An email-only trial endpoint returns 401 for a valid Telegram
            // session; that must NOT delete the user's Telegram login.
            if (status == 401 && path == "/api/account/overview")
                session.clear()
            val stream = if (status in 200..299) conn.inputStream else conn.errorStream
            val content = stream?.use { input ->
                // Bound memory and do not show arbitrary server errors to the user.
                val result = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    require(result.size() + count <= 262_144) {
                        "Invalid response size"
                    }
                    result.write(buffer, 0, count)
                }
                result.toString(StandardCharsets.UTF_8.name())
            }.orEmpty()
            val parsed = runCatching { JSONObject(content) }.getOrNull()
            if (path == "/api/mobile-auth/exchange" && status == 200 &&
                parsed?.optBoolean("authenticated") == true) {
                val name = parsed.optString("cookie_name")
                val token = parsed.optString("session")
                // Do not trust arbitrary cookie names in a server response.
                if (name == emailCookie || name == telegramCookie) {
                    session.saveSession(name, token)
                } else error("Unexpected native account session type")
            }
            return Reply(status, parsed)
        } finally {
            conn.disconnect()
        }
    }
}
