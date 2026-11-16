package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class NativeCabinetAuthPolicyTest {
    private val email = NativeCabinetAuthPolicy.EMAIL_COOKIE
    private val telegram = NativeCabinetAuthPolicy.TELEGRAM_COOKIE

    @Test fun unrelated401NeverLogsOutValidTelegramOrEmailUser() {
        for (cookie in listOf(email, telegram)) {
            for (path in listOf("/api/account/overview", "/api/trial/status",
                    "/api/shop/config", "/api/mobile-auth/config")) {
                assertFalse(NativeCabinetAuthPolicy.shouldInvalidateSession(
                    cookie, path, 401, null))
                assertFalse(NativeCabinetAuthPolicy.shouldInvalidateSession(
                    cookie, path, 403, null))
            }
        }
    }

    @Test fun matchingIdentityEndpointMayExpireOnlyItsOwnCookie() {
        assertTrue(NativeCabinetAuthPolicy.shouldInvalidateSession(
            email, "/api/email-auth/account", 200, false))
        assertTrue(NativeCabinetAuthPolicy.shouldInvalidateSession(
            telegram, "/api/telegram/account", 401, null))
        assertFalse(NativeCabinetAuthPolicy.shouldInvalidateSession(
            telegram, "/api/email-auth/account", 200, false))
        assertFalse(NativeCabinetAuthPolicy.shouldInvalidateSession(
            email, "/api/telegram/account", 401, null))
    }

    @Test fun transientFailuresDoNotEraseAnAuthenticatedAccount() {
        for (status in listOf(200, 429, 500, 502, 503, 504)) {
            assertFalse(NativeCabinetAuthPolicy.shouldInvalidateSession(
                email, "/api/email-auth/account", status, true))
            assertFalse(NativeCabinetAuthPolicy.shouldInvalidateSession(
                telegram, "/api/telegram/account", status, true))
        }
        assertFalse(NativeCabinetAuthPolicy.shouldInvalidateSession(
            email, "/api/email-auth/account", 200, null))
        assertFalse(NativeCabinetAuthPolicy.shouldInvalidateSession(
            "unknown-session", "/api/email-auth/account", 401, false))
    }
}
