package app.vainah.vpn

import org.junit.Assert.*
import org.junit.Test

class CabinetServicePathsTest {
    @Test fun supportDeviceAndReminderRoutesAreExplicitlyBounded() {
        val read = listOf(
            "/api/support/config", "/api/support/tickets",
            "/api/account/devices", "/api/account/devices/limits",
            "/api/account/reminder-preference"
        )
        assertTrue(read.all(CabinetServicePaths::allowRead))
        assertTrue(CabinetServicePaths.allowWrite("/api/support/tickets"))
        assertTrue(CabinetServicePaths.allowWrite("/api/account/devices"))
        assertTrue(CabinetServicePaths.allowWrite("/api/account/reminder-preference"))
        assertFalse(CabinetServicePaths.allowWrite("/api/support/config"))
        assertFalse(CabinetServicePaths.allowWrite("/api/account/devices/limits"))
    }

    @Test fun hostileUrisAndOperatorEndpointsAreNeverAuthorized() {
        val malicious = listOf(
            "/api/support/operator/tickets",
            "/api/support/tickets/a/messages/../operator/tickets",
            "/api/account/devices/../../admin",
            "/api/support/tickets/a",
            "https://evil.test/api/account/devices",
            "/api/account/devices?session=secret",
            "//example.invalid/api/support/tickets",
            "/api/shop/payment",
            "/api/shop/webhooks/rollypay"
        )
        for (path in malicious) {
            assertFalse("Unexpected route: $path",
                CabinetServicePaths.allowRead(path))
            assertFalse("Unexpected route: $path",
                CabinetServicePaths.allowWrite(path))
        }
    }

    @Test fun ticketMessageRouteValidatesOnlyRealShortOpaqueId() {
        val id = "AbCdEfGhIjKlMnOpQrSt"
        val path = CabinetServicePaths.messagePath(id)
        assertNotNull(path)
        assertTrue(CabinetServicePaths.allowRead(path!!))
        assertTrue(CabinetServicePaths.allowWrite(path))
        assertNull(CabinetServicePaths.messagePath("../../../admin"))
        assertNull(CabinetServicePaths.messagePath("short"))
        assertNull(CabinetServicePaths.messagePath("b".repeat(40)))
    }

    @Test fun privateVpnUrlsAreBlockedInSupportDrafts() {
        assertFalse(SupportDraftPolicy.safe("Вот моя ссылка vless://secret@host", 12))
        assertFalse(SupportDraftPolicy.safe(
            "Моя ссылка subscription_url: https://secret", 12))
        assertFalse(SupportDraftPolicy.safe("Ключ https://site.invalid", 12))
        assertFalse(SupportDraftPolicy.safe("коротко", 12))
        assertTrue(SupportDraftPolicy.safe(
            "VPN прекращает подключение при переходе с Wi-Fi на LTE.", 12))
        assertTrue(SupportDraftPolicy.safe("Спасибо за ответ", 4))
        assertTrue(SupportDraftPolicy.category("payment"))
        assertFalse(SupportDraftPolicy.category("operator"))
    }
}
