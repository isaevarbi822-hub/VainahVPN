package app.vainah.vpn

import java.security.MessageDigest

/** Local-only comparison of bearer credentials; never logs or displays URL contents. */
object SubscriptionLinkComparison {
    enum class Match { NO_SAVED_LINK, INVALID_CANDIDATE, SAME, DIFFERENT }

    fun check(saved: String?, pasted: String): Match {
        val current = saved?.let(SubscriptionInput::validate) ?: return Match.NO_SAVED_LINK
        val other = SubscriptionInput.validate(pasted) ?: return Match.INVALID_CANDIDATE
        return if (MessageDigest.isEqual(
                current.toByteArray(Charsets.UTF_8),
                other.toByteArray(Charsets.UTF_8)
            )) Match.SAME else Match.DIFFERENT
    }

    fun message(result: Match): String = when (result) {
        Match.NO_SAVED_LINK -> "В Vainah VPN ещё нет сохранённой подписки."
        Match.INVALID_CANDIDATE ->
            "Вставленный текст не похож на полную HTTPS-подписку или VLESS REALITY-ключ."
        Match.SAME ->
            "Ссылки совпадают полностью. Причина HTTP 403 не в разной сохранённой ссылке."
        Match.DIFFERENT ->
            "Ссылки отличаются. Возможно, Vainah VPN использует старую подписку. " +
            "Проверь актуальную ссылку в H1Cloud и замени её вручную, если нужно."
    }
}
