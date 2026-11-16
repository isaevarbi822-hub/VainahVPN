package app.vainah.vpn

/**
 * HTTP 401 from an unrelated account/trial endpoint does NOT prove the signed
 * native session expired. In particular, a Telegram identity without a linked
 * verified email legitimately receives 401 from email-only resources.
 *
 * Only the authenticated identity's own status endpoint can invalidate it.
 */
internal object NativeCabinetAuthPolicy {
    const val EMAIL_COOKIE = "__Host-vainah_email_session"
    const val TELEGRAM_COOKIE = "__Host-vainah_session"

    fun shouldInvalidateSession(
        activeCookie: String?,
        requestPath: String,
        httpStatus: Int,
        authenticated: Boolean?
    ): Boolean {
        val identityPath = when (activeCookie) {
            EMAIL_COOKIE -> "/api/email-auth/account"
            TELEGRAM_COOKIE -> "/api/telegram/account"
            else -> return false
        }
        return requestPath == identityPath &&
            (httpStatus == 401 ||
                (httpStatus == 200 && authenticated == false))
    }
}
