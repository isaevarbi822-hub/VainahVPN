package app.vainah.vpn

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** Offline synthetic fixtures only: do not fake actual tariff prices in UI. */
class NativeCabinetCatalogTest {
    private fun trial(): JSONObject = JSONObject()
        .put("id", "trial-free").put("title", "Пробный день")
        .put("days", 1).put("devices", 2).put("traffic_gb", 10)
        .put("price_rub", "0.00").put("category", "trial")
        .put("checkout_path", "/trial.html").put("checkout_supported", false)

    private fun paid(id: String = "30", price: String = "149.00"): JSONObject =
        JSONObject().put("id", id).put("title", "1 месяц")
            .put("days", 30).put("devices", 3)
            .put("price_rub", price).put("category", "personal")
            .put("checkout_supported", true)
            .put("checkout_path", "/checkout.html?plan=$id")

    private fun parse(vararg plans: JSONObject): NativeCabinetCatalog.Snapshot =
        NativeCabinetCatalog.parse(JSONObject()
            .put("plans", JSONArray().apply { plans.forEach { put(it) } }).toString())

    @Test fun accountApiAndOAuthNeverTargetTheStaticCheckoutSite() {
        assertEquals("https://vainahvpn-python-preview.onrender.com",
            NativeCabinetCatalog.API_ORIGIN)
        assertEquals("https://vainahvpn.onrender.com",
            NativeCabinetCatalog.ORIGIN)
        assertNotEquals(NativeCabinetCatalog.API_ORIGIN,
            NativeCabinetCatalog.ORIGIN)
    }

    @Test fun freeTrialIsSeparateAndNotConvertedIntoPaidCheckout() {
        val catalog = parse(trial(), paid())
        assertEquals(2, catalog.count)
        assertEquals("Пробный день", catalog.trial?.title)
        assertEquals("Бесплатно", catalog.trial?.priceLabel)
        assertEquals(1, catalog.paid.size)
        assertNull(NativeCabinetCatalog.checkoutUrl(catalog.trial!!, true))
    }

    @Test fun realPricesArePassedThroughWithoutLocalRecalculation() {
        val plan = parse(trial(), paid(price = "149.00")).paid.single()
        assertEquals("149.00 ₽", plan.priceLabel)
        assertEquals(3, plan.devices)
        assertEquals("https://vainahvpn.onrender.com/checkout.html?plan=30",
            NativeCabinetCatalog.checkoutUrl(plan, true))
        assertNull(NativeCabinetCatalog.checkoutUrl(plan, false))
    }

    @Test fun backendCheckoutPathsCannotEscapeOfficialHost() {
        val attack = paid().put("checkout_path",
            "https://fraud.example.invalid/payment")
        val parsed = parse(trial(), attack)
        assertEquals(0, parsed.paid.size)
        val valid = parse(paid()).paid.single()
        assertNull(NativeCabinetCatalog.checkoutUrl(
            valid.copy(checkoutPath = "//fraud.example.invalid"), true
        ))
        assertNull(NativeCabinetCatalog.checkoutUrl(
            valid.copy(id = "30?redirect=evil"), true
        ))
    }

    @Test fun forgedTrialAndFreePaidPlansAreNeverShownAsAvailable() {
        val forged = trial().put("checkout_supported", true)
            .put("checkout_path", "/checkout.html?plan=trial-free")
        val freePaid = paid(id = "100", price = "0.00")
        val loaded = parse(forged, freePaid, paid())
        assertNull(loaded.trial)
        assertEquals(listOf("30"), loaded.paid.map { it.id })
    }

    @Test fun malformedAndDuplicateRowsCannotCreateInvalidCheckout() {
        val rows = listOf(
            paid(),
            paid(),
            paid("not valid", "149.00"),
            paid("10", "-1.00"),
            paid("11", "199.00").put("days", 0)
        )
        val parsed = parse(*rows.toTypedArray())
        assertEquals(1, parsed.paid.size)
        assertEquals("30", parsed.paid.single().id)
    }

    @Test fun emptyOrOverlargeCatalogIsRejected() {
        assertThrows(IllegalArgumentException::class.java) {
            parse()
        }
        assertThrows(IllegalArgumentException::class.java) {
            NativeCabinetCatalog.parse("x".repeat(262_145))
        }
    }
}
