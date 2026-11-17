package app.vainah.vpn

import java.net.URI
import java.net.URLDecoder
import java.util.Locale
import java.util.UUID

/**
 * Parse supported and display-only VLESS subscription entries without exposing
 * their credentials in UI. TCP/REALITY, TCP/TLS, and gRPC profiles
 * may be passed to the bundled libbox engine after local validation.
 * XHTTP is connectable ONLY when the checked XHTTP-enabled native AAR is bundled.
 */
object SubscriptionNodeSupport {
    data class Details(
        val transport: String,
        val security: String,
        val connectable: Boolean,
        val rejectionCode: String? = null,
    ) {
        val subtitle: String
            get() = "VLESS / ${transport.uppercase(Locale.ROOT)} / " +
                security.uppercase(Locale.ROOT)
    }

    fun inspect(raw: String): Details? = runCatching {
        if (raw.length !in 1..8192) return@runCatching null
        val uri = URI(raw)
        if (uri.scheme != "vless" || uri.host.isNullOrBlank() ||
            uri.host!!.length > 253 || uri.port !in 1..65535) return@runCatching null
        val id = uri.rawUserInfo ?: return@runCatching null
        if (!id.matches(Regex("[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")))
            return@runCatching null
        UUID.fromString(id)
        val params = uri.rawQuery.orEmpty().split('&').mapNotNull { part ->
            val p = part.indexOf('=')
            if (p <= 0) null
            else URLDecoder.decode(part.substring(0, p), "UTF-8").lowercase(Locale.ROOT) to
                URLDecoder.decode(part.substring(p + 1), "UTF-8")
        }.toMap()
        val security = params["security"]?.lowercase(Locale.ROOT) ?: "none"
        if (security !in setOf("tls", "reality")) return@runCatching null
        if (security == "reality" &&
            (params["pbk"].isNullOrBlank() || params["sni"].isNullOrBlank())) return@runCatching null
        val network = (params["type"] ?: "tcp").lowercase(Locale.ROOT)
        if (network !in setOf("tcp", "raw", "grpc", "xhttp", "splithttp")) return@runCatching null
        val normalized = when(network) {
            "raw" -> "tcp"
            "splithttp" -> "xhttp"
            else -> network
        }
        val parsed = runCatching { VlessRealityConfig.outbound(raw) }
        val nativeTransportPresent = normalized != "xhttp" ||
            BuildConfig.VAINAH_XHTTP_ENGINE_ENABLED
        val reason = when {
            !nativeTransportPresent -> "native_xhttp_missing"
            parsed.isFailure -> safeProfileFailure(parsed.exceptionOrNull())
            else -> null
        }
        Details(normalized, security, parsed.isSuccess && nativeTransportPresent, reason)
    }.getOrNull()

    /**
     * Classify our own fixed parser exceptions. Never export Throwable text,
     * node authorities, SNI, UUIDs or other private subscription details.
     */
    private fun safeProfileFailure(error: Throwable?): String = when (error?.message) {
        "Unsupported XHTTP option" -> "xhttp_extra_unsupported"
        "Unsupported XHTTP xmux setting" -> "xhttp_xmux_unknown_field"
        "Conflicting XHTTP xmux limits" -> "xhttp_xmux_conflicting_limits"
        "Invalid XHTTP xmux range" -> "xhttp_xmux_invalid_range"
        "Invalid XHTTP xmux keepalive" -> "xhttp_xmux_invalid_keepalive"
        "Duplicate XHTTP xmux setting" -> "xhttp_xmux_duplicate_key"
        "Invalid XHTTP xmux" -> "xhttp_xmux_invalid"
        "Invalid XHTTP xmux type" -> "xhttp_xmux_invalid_type"
        "Invalid XHTTP xmux JSON" -> "xhttp_xmux_invalid_json"
        "XHTTP xmux too large" -> "xhttp_xmux_too_large"
        "Too many XHTTP xmux fields" -> "xhttp_xmux_too_many_fields"
        "Invalid XHTTP mode", "Invalid XHTTP path", "Invalid XHTTP host",
        "Invalid XHTTP padding", "Invalid XHTTP extra", "XHTTP extra too large",
        "Too many XHTTP options", "Invalid XHTTP option value",
        "Invalid XHTTP headers", "Invalid XHTTP header name",
        "Invalid XHTTP header value", "XHTTP headers too large",
        "Invalid XHTTP boolean", "Invalid noGRPCHeader" -> "xhttp_options_invalid"
        "VLESS Vision flow requires raw TCP", "Unsupported VLESS flow" ->
            "vless_flow_incompatible"
        "Invalid ALPN" -> "tls_alpn_invalid"
        else -> "profile_invalid"
    }

    private val rejectionCodes = setOf(
        "ok", "profile_unrecognized", "profile_invalid", "native_xhttp_missing",
        "xhttp_extra_unsupported", "xhttp_xmux_unknown_field",
        "xhttp_xmux_conflicting_limits", "xhttp_xmux_invalid_range",
        "xhttp_xmux_invalid_keepalive", "xhttp_xmux_duplicate_key", "xhttp_xmux_invalid",
        "xhttp_xmux_invalid_type", "xhttp_xmux_invalid_json", "xhttp_xmux_too_large",
        "xhttp_xmux_too_many_fields", "xhttp_options_invalid",
        "vless_flow_incompatible", "tls_alpn_invalid"
    )

    fun safeRejectionCode(candidate: String?): String =
        candidate?.takeIf { it in rejectionCodes } ?: "unknown"

    fun safeBlockMessage(details: Details?): String = when (details?.rejectionCode) {
        "native_xhttp_missing" ->
            "Сборка APK не содержит проверенное XHTTP-ядро. Установи сборку с sing-box-lx."
        "xhttp_extra_unsupported" ->
            "Профиль содержит дополнительную опцию XHTTP, которую этот движок не поддерживает. " +
                "Нужно проверить исходные настройки сервера H1Cloud; параметры нельзя удалять автоматически."
        "xhttp_xmux_unknown_field" ->
            "В XMUX есть неподдерживаемое поле. Проверь экспорт H1Cloud и версию транспорта."
        "xhttp_xmux_conflicting_limits" ->
            "XMUX одновременно задаёт два активных ограничения соединений. " +
                "Нужна правка конфигурации сервера."
        "xhttp_xmux_invalid_range" ->
            "В XMUX есть неверный числовой диапазон. Проверь экспорт H1Cloud."
        "xhttp_xmux_invalid_keepalive" ->
            "В XMUX указан неверный интервал keepalive."
        "xhttp_xmux_duplicate_key" ->
            "Параметр XMUX указан дважды под разными именами."
        "xhttp_xmux_invalid" ->
            "В настройках XMUX указан несовместимый или неправильный параметр. " +
                "Проверь экспорт сервера в H1Cloud."
        "xhttp_xmux_invalid_type" ->
            "XMUX должен быть объектом настроек. Получен другой тип данных. " +
                "Скопируй отчёт на вкладке «Диагностика»."
        "xhttp_xmux_invalid_json" ->
            "XMUX передан текстом, который не удалось разобрать как объект JSON. " +
                "Скопируй отчёт на вкладке «Диагностика»."
        "xhttp_xmux_too_large" ->
            "Объект XMUX превышает допустимый размер. " +
                "Скопируй отчёт на вкладке «Диагностика»."
        "xhttp_xmux_too_many_fields" ->
            "В объекте XMUX слишком много полей. " +
                "Скопируй отчёт на вкладке «Диагностика»."
        "xhttp_options_invalid" ->
            "Параметры XHTTP не прошли проверку. Проверь режим, путь и дополнительные настройки сервера."
        "vless_flow_incompatible" ->
            "В профиле указан VLESS flow, несовместимый с XHTTP. Проверь конфигурацию сервера."
        "tls_alpn_invalid" ->
            "В профиле указан некорректный список TLS ALPN."
        else ->
            "Профиль этого сервера не прошёл локальную проверку. " +
                "Другие серверы можно подключать; обновление подписки само по себе не исправляет формат."
    }

    fun canConnect(raw: String): Boolean = inspect(raw)?.connectable == true
}
