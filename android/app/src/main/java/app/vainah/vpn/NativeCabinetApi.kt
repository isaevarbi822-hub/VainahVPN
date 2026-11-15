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

    fun save(session: String) {
        require(session.matches(Regex("[A-Za-z0-9_-]{20,512}\\.[0-9a-f]{64}")))
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val ciphertext = cipher.doFinal(session.toByteArray(StandardCharsets.UTF_8))
        prefs.edit().putString("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .putString("sealed", Base64.encodeToString(ciphertext, Base64.NO_WRAP))
            .commit()
    }

    fun read(): String? = runCatching {
        val iv = prefs.getString("iv", null) ?: return null
        val sealed = prefs.getString("sealed", null) ?: return null
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(
            128, Base64.decode(iv, Base64.NO_WRAP)))
        val session = String(cipher.doFinal(Base64.decode(
            sealed, Base64.NO_WRAP)), StandardCharsets.UTF_8)
        session.takeIf { it.matches(Regex("[A-Za-z0-9_-]{20,512}\\.[0-9a-f]{64}")) }
    }.getOrNull()

    fun clear() {
        prefs.edit().clear().commit()
    }
}

/** Same-origin, no-redirect, no-cleartext native JSON requests. */
internal class NativeCabinetApi(context: Context) {
    private val session = NativeCabinetSession(context)
    private val cookieName = "__Host-vainah_email_session"
    private val accepted = setOf(
        "/api/site/tariffs", "/api/shop/config",
        "/api/trial/config", "/api/trial/status",
        "/api/email-auth/account", "/api/account/overview"
    )
    private val writes = setOf(
        "/api/email-auth/request", "/api/email-auth/verify",
        "/api/email-auth/logout", "/api/trial/claim"
    )

    data class Reply(val status: Int, val json: JSONObject?) {
        val ok: Boolean get() = status in 200..299
    }

    fun hasSession(): Boolean = session.read() != null
    fun forgetSession() = session.clear()

    fun get(path: String): Reply {
        require(path in accepted)
        return request(path, null)
    }

    fun post(path: String, body: JSONObject = JSONObject()): Reply {
        require(path in writes)
        return request(path, body)
    }

    private fun request(path: String, payload: JSONObject?): Reply {
        val address = URL(NativeCabinetCatalog.ORIGIN + path)
        require(address.protocol == "https" && address.host == "vainahvpn.onrender.com"
            && address.port == -1)
        val conn = address.openConnection() as HttpsURLConnection
        conn.instanceFollowRedirects = false
        conn.connectTimeout = 9_000
        conn.readTimeout = 9_000
        conn.useCaches = false
        conn.setRequestProperty("Accept", "application/json")
        conn.setRequestProperty("User-Agent", "VainahVPN-Android-NativeCabinet")
        session.read()?.let {
            conn.setRequestProperty("Cookie", "$cookieName=$it")
        }
        try {
            if (payload != null) {
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.setRequestProperty("Origin", NativeCabinetCatalog.ORIGIN)
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
                    .firstOrNull { it.startsWith("$cookieName=") }
                    ?.substringAfter("=")?.substringBefore(";")
                if (cookie != null) session.save(cookie)
            }
            if (status == 401 && path != "/api/email-auth/request" &&
                path != "/api/email-auth/verify") session.clear()
            val stream = if (status in 200..299) conn.inputStream else conn.errorStream
            val content = stream?.use { input ->
                // Bound memory and do not show arbitrary server errors to the user.
                val result = input.readNBytes(262_145)
                require(result.size <= 262_144) { "Invalid response size" }
                String(result, StandardCharsets.UTF_8)
            }.orEmpty()
            return Reply(status, runCatching {
                JSONObject(content)
            }.getOrNull())
        } finally {
            conn.disconnect()
        }
    }
}
