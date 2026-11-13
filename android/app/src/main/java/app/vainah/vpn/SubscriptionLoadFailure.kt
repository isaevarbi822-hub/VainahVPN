package app.vainah.vpn

import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLException

/**
 * Public, credential-safe explanations for HTTPS subscription failures.
 * Never display Throwable.message: Java may include a private subscription URL.
 */
class SubscriptionHttpStatus(
    val status: Int,
    val category: SubscriptionDenial.Kind = SubscriptionDenial.Kind.UNKNOWN,
    val source: SubscriptionOrigin.Kind = SubscriptionOrigin.Kind.NONE
) : Exception()

/** No host, full URL or private subscription token is attached to this error. */
class SubscriptionRequestTimeout(
    val source: SubscriptionOrigin.Kind
) : SocketTimeoutException()

object SubscriptionLoadFailure {
    fun explain(error: Throwable): String = when (error) {
        is SubscriptionHttpStatus -> when (error.status) {
            401 -> "HTTP 401: сервер отклонил авторизацию. " +
                SubscriptionOrigin.label(error.source) +
                " Это не доказательство окончания подписки."
            403 -> "HTTP 403: сервер подписки отклонил запрос Vainah VPN. " +
                SubscriptionOrigin.label(error.source) + " " +
                "Подписка может работать в другом VPN-клиенте. " +
                SubscriptionDenial.label(error.category) +
                " Это не подтверждает окончание подписки."
            404, 410 -> "HTTP ${error.status}: сервер не нашёл запрошенный адрес подписки. Проверь ссылку в кабинете."
            429 -> "HTTP 429: сервер временно ограничил число запросов. Ранее загруженные серверы сохранены."
            in 300..399 -> "HTTP ${error.status}: сервер перенаправляет подписку. Автоматический переход заблокирован ради защиты ссылки."
            in 500..599 -> "HTTP ${error.status}: сервер подписки ответил ошибкой. " +
                SubscriptionOrigin.label(error.source)
            else -> "HTTP ${error.status}: сервер не отдал список VPN-серверов."
        }
        is UnknownHostException -> "Ошибка DNS: домен подписки сейчас не определяется."
        is SubscriptionRequestTimeout -> "Тайм-аут HTTPS: " +
            SubscriptionOrigin.label(error.source) + " " +
            if (error.source == SubscriptionOrigin.Kind.PYTHON_RENDER)
                "Бесплатный Render может просыпаться после простоя. " +
                "В этой версии ожидание ответа Render увеличено до 85 секунд."
            else "Сервер не ответил в установленное время. " +
                "Проверь доступность подписки через Happ и попробуй позднее."
        is SocketTimeoutException -> "Тайм-аут HTTPS: сервер не ответил. Попробуй обновить позднее."
        is ConnectException -> "Не удалось подключиться к серверу подписки по HTTPS."
        is SSLException -> "Ошибка TLS: не удалось проверить защищённое соединение с H1Cloud."
        is IllegalArgumentException -> "Ссылка или формат подписки не поддерживается этим приложением."
        else -> "Не удалось обновить H1Cloud-серверы. Ранее загруженные локации сохранены."
    }
}
