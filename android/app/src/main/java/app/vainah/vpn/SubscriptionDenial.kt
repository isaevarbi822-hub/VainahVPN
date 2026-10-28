package app.vainah.vpn

import java.io.InputStream
import java.net.HttpURLConnection
import java.util.Locale

/**
 * Read only bounded public indicators from a denied HTTP response.
 * Error bodies may include bearer URLs, tokens and private IPs; NEVER return
 * the body, arbitrary response headers, or exception messages to UI/logs.
 * Categories are heuristic signals, not authorization or entitlement proof.
 */
object SubscriptionDenial {
    enum class Kind { EDGE_CHALLENGE, DEVICE_LIMIT, HWID_REQUIRED, CLIENT_POLICY,
        AUTHORIZATION, UNKNOWN }

    fun classify(body: String, cloudflareMarker: Boolean = false): Kind {
        val text = body.take(4096).lowercase(Locale.ROOT)
        return when {
            cloudflareMarker || listOf("cloudflare", "cf-error", "just a moment",
                "attention required", "captcha challenge").any { it in text } ->
                Kind.EDGE_CHALLENGE
            listOf("device limit", "too many devices", "max devices",
                "device quota", "лимит устройств", "devices limit",
                "device count exceeded").any { it in text } -> Kind.DEVICE_LIMIT
            listOf("hwid required", "missing hwid", "invalid hwid",
                "unknown hwid", "hwid mismatch", "hwid not allowed",
                "идентификатор устройства").any { it in text } -> Kind.HWID_REQUIRED
            listOf("user-agent", "user agent", "unsupported client",
                "client not allowed", "unsupported app",
                "application not allowed").any { it in text } -> Kind.CLIENT_POLICY
            listOf("invalid token", "missing token", "unauthorized",
                "authentication required", "invalid subscription",
                "access denied", "forbidden").any { it in text } ->
                Kind.AUTHORIZATION
            else -> Kind.UNKNOWN
        }
    }

    fun fromResponse(connection: HttpURLConnection): Kind {
        val edgeMarker = connection.getHeaderField("cf-ray") != null
        val stream = runCatching { connection.errorStream }.getOrNull()
        if (stream == null) return if (edgeMarker) Kind.EDGE_CHALLENGE else Kind.UNKNOWN
        return runCatching {
            val bytes = stream.use { readLimited(it, 4096) }
            classify(String(bytes, Charsets.UTF_8), edgeMarker)
        }.getOrDefault(if (edgeMarker) Kind.EDGE_CHALLENGE else Kind.UNKNOWN)
    }

    private fun readLimited(stream: InputStream, limit: Int): ByteArray {
        val output = java.io.ByteArrayOutputStream()
        val buffer = ByteArray(512)
        while (output.size() < limit) {
            val take = minOf(buffer.size, limit - output.size())
            val size = stream.read(buffer, 0, take)
            if (size < 0) break
            if (size == 0) continue
            output.write(buffer, 0, size)
        }
        return output.toByteArray()
    }

    fun label(kind: Kind): String = when (kind) {
        Kind.EDGE_CHALLENGE ->
            "Похоже на отказ защитного фильтра сайта (например, антибот-проверка)."
        Kind.DEVICE_LIMIT ->
            "В ответе упоминается лимит устройств. Проверь разрешённые устройства в H1Cloud."
        Kind.HWID_REQUIRED ->
            "В ответе упоминается HWID. Проверь разрешение Vainah VPN в панели H1Cloud."
        Kind.CLIENT_POLICY ->
            "В ответе упоминается тип клиента или User-Agent. Проверь разрешённые приложения у провайдера."
        Kind.AUTHORIZATION ->
            "В ответе упоминается авторизация или токен. Проверь, что добавлена актуальная ссылка."
        Kind.UNKNOWN ->
            "Сервер не сообщил распознаваемую причину отказа."
    }
}
